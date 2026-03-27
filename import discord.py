import os
import math
import json
import time
import requests
import discord
from discord.ext import tasks, commands
from dotenv import load_dotenv
from pathlib import Path
from urllib.parse import urlparse

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID")

if not TOKEN:
    raise ValueError("Missing DISCORD_TOKEN in .env")

if not CHANNEL_ID_RAW or not CHANNEL_ID_RAW.isdigit():
    raise ValueError("CHANNEL_ID must be a numeric value in .env")

CHANNEL_ID = int(CHANNEL_ID_RAW)

CLIENT_ID = os.getenv("GOV_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOV_CLIENT_SECRET")
TOKEN_URL = os.getenv("GOV_TOKEN_URL")
API_URL = os.getenv("GOV_API_URL")
AUTO_DELETE_SECONDS = int(os.getenv("BOT_DELETE_AFTER_SECONDS", "60"))
DM_COMMAND_RESPONSES = os.getenv("BOT_DM_RESPONSES", "false").lower() == "true"
DELETE_USER_COMMAND_MESSAGES = os.getenv("BOT_DELETE_USER_COMMANDS", "true").lower() == "true"

SETTINGS_PATH = Path(__file__).with_name("fuel_settings.json")
DEFAULT_SETTINGS = {
    "lat": 52.9225,
    "lon": -1.4746,
    "location_name": "Derby, UK",
    "radius_miles": 10.0,
}

PUBLIC_FEEDS = [
    "https://storelocator.asda.com/fuel_prices_data.json",
    "https://www.tesco.com/fuel_prices/fuel_prices_data.json",
    "https://www.morrisons.com/fuel-prices/fuel.json",
]

LAST_BOT_MESSAGE_BY_CHANNEL = {}
PENDING_SELECTIONS_BY_USER = {}
SELECTION_TTL_SECONDS = 600


def load_settings():
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    return {
        "lat": float(data.get("lat", DEFAULT_SETTINGS["lat"])),
        "lon": float(data.get("lon", DEFAULT_SETTINGS["lon"])),
        "location_name": str(data.get("location_name", DEFAULT_SETTINGS["location_name"])),
        "radius_miles": max(0.1, float(data.get("radius_miles", DEFAULT_SETTINGS["radius_miles"]))),
    }


def save_settings(settings):
    with SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


async def send_channel_message(channel, content, suppress_embeds=False, delete_previous=False, delete_after=None):
    if delete_previous:
        previous = LAST_BOT_MESSAGE_BY_CHANNEL.get(channel.id)
        if previous:
            try:
                await previous.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

    if delete_after is None:
        delete_after = AUTO_DELETE_SECONDS if AUTO_DELETE_SECONDS > 0 else None

    msg = await channel.send(
        content,
        suppress_embeds=suppress_embeds,
        delete_after=delete_after,
    )

    if delete_previous:
        LAST_BOT_MESSAGE_BY_CHANNEL[channel.id] = msg

    return msg


async def reply(ctx, content, suppress_embeds=False):
    if DM_COMMAND_RESPONSES:
        try:
            dm_channel = await ctx.author.create_dm()
            return await send_channel_message(dm_channel, content, suppress_embeds=suppress_embeds)
        except discord.Forbidden:
            pass

    return await send_channel_message(ctx.channel, content, suppress_embeds=suppress_embeds)


async def cleanup_user_command(ctx):
    if not DELETE_USER_COMMAND_MESSAGES:
        return

    if ctx.guild is None:
        return

    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass


@bot.before_invoke
async def before_any_command(ctx):
    await cleanup_user_command(ctx)


def get_access_token():
    if not TOKEN_URL:
        raise RuntimeError("GOV_TOKEN_URL is not configured")

    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("GOV_CLIENT_ID/GOV_CLIENT_SECRET are not configured")

    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }

    try:
        r = requests.post(TOKEN_URL, data=data, timeout=15)
    except requests.RequestException as exc:
        host = urlparse(TOKEN_URL).hostname or "<invalid GOV_TOKEN_URL>"
        raise RuntimeError(
            f"Could not connect to token endpoint host '{host}'. "
            "Check GOV_TOKEN_URL, DNS, VPN/firewall, and internet connection."
        ) from exc

    r.raise_for_status()
    return r.json()["access_token"]


def distance_miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geocode_location(query):
    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "fuel-discord-bot/1.0"
    }
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
    }

    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    results = r.json()

    if not results:
        return None

    top = results[0]
    return {
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
        "name": top.get("display_name", query),
    }


def normalize_station(station):
    location = station.get("location") or {}
    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is None or lon is None:
        return None

    prices = station.get("prices") or {}
    brand = station.get("brand", "Unknown")
    address = station.get("address", "No address")

    return {
        "name": f"{brand} - {address}",
        "lat": float(lat),
        "lon": float(lon),
        "petrol": prices.get("E10"),
        "super_unleaded": prices.get("E5"),
        "diesel": prices.get("B7"),
    }


def get_prices():
    settings = load_settings()
    center_lat = settings["lat"]
    center_lon = settings["lon"]
    radius_miles = settings["radius_miles"]

    stations_data = None

    if TOKEN_URL and API_URL:
        try:
            token = get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            stations_url = f"{API_URL.rstrip('/')}/stations"
            r = requests.get(stations_url, headers=headers, timeout=20)
            r.raise_for_status()
            stations_data = r.json()
        except Exception:
            stations_data = None

    if stations_data is None:
        combined_stations = []
        last_error = None
        for feed_url in PUBLIC_FEEDS:
            try:
                r = requests.get(feed_url, timeout=20)
                r.raise_for_status()
                combined_stations.extend(r.json().get("stations", []))
            except requests.RequestException as exc:
                last_error = exc

        if not combined_stations:
            host = urlparse(PUBLIC_FEEDS[0]).hostname or "<unknown>"
            raise RuntimeError(
                f"Could not load any fuel feed (example host: '{host}'). "
                "Check DNS, VPN/firewall, and internet connection."
            ) from last_error

        stations_data = {"stations": combined_stations}

    stations = []
    for raw_station in stations_data.get("stations", []):
        station = normalize_station(raw_station)
        if not station:
            continue

        dist = distance_miles(center_lat, center_lon, station["lat"], station["lon"])
        if dist <= radius_miles:
            station["distance_miles"] = dist
            station["maps_url"] = f"https://www.google.com/maps?q={station['lat']},{station['lon']}"
            stations.append(station)

    return stations


def build_report_message(stations):
    settings = load_settings()
    petrol_stations = [s for s in stations if s["petrol"] is not None]
    super_stations = [s for s in stations if s["super_unleaded"] is not None]
    diesel_stations = [s for s in stations if s["diesel"] is not None]

    cheapest_petrol = min(petrol_stations, key=lambda x: x["petrol"], default=None)
    cheapest_super = min(super_stations, key=lambda x: x["super_unleaded"], default=None)
    cheapest_diesel = min(diesel_stations, key=lambda x: x["diesel"], default=None)

    msg = (
        "⛽ **Nearby Fuel Prices** 🇬🇧\n"
        f"📍 Center: `{settings['location_name']}` ({settings['lat']:.5f}, {settings['lon']:.5f}) | Radius: `{settings['radius_miles']:.1f} miles`\n\n"
    )

    if cheapest_petrol:
        msg += (
            f"🟢 Unleaded (E10): **{cheapest_petrol['petrol']}p/L**\n"
            f"{cheapest_petrol['name']} ({cheapest_petrol['distance_miles']:.1f} miles)\n"
            f"🗺️ <{cheapest_petrol['maps_url']}>\n\n"
        )

    if cheapest_super:
        msg += (
            f"🔵 Super Unleaded (E5): **{cheapest_super['super_unleaded']}p/L**\n"
            f"{cheapest_super['name']} ({cheapest_super['distance_miles']:.1f} miles)\n"
            f"🗺️ <{cheapest_super['maps_url']}>\n\n"
        )

    if cheapest_diesel:
        msg += (
            f"🟡 Diesel (B7): **{cheapest_diesel['diesel']}p/L**\n"
            f"{cheapest_diesel['name']} ({cheapest_diesel['distance_miles']:.1f} miles)\n"
            f"🗺️ <{cheapest_diesel['maps_url']}>\n"
        )

    return msg


def get_top_stations_by_fuel(stations, fuel_key, limit=5):
    filtered = [s for s in stations if s.get(fuel_key) is not None]
    filtered.sort(key=lambda s: s[fuel_key])
    return filtered[:limit]


def build_top5_message(title, fuel_key, stations):
    if not stations:
        return f"No stations found with {title} prices in your radius."

    msg = f"⛽ **Top {len(stations)} cheapest {title} stations**\n\n"
    for i, station in enumerate(stations, start=1):
        msg += (
            f"`{i}.` **{station[fuel_key]}p/L** - {station['name']} "
            f"({station['distance_miles']:.1f} miles)\n"
        )

    msg += "\nReply with `!pick <number>` to get the Google Maps link."
    return msg


@tasks.loop(hours=24)
async def daily_post():
    print("Fetching fuel prices...")
    channel = await bot.fetch_channel(CHANNEL_ID)
    try:
        stations = get_prices()
    except Exception as exc:
        print(f"Fuel price fetch failed: {exc}")
        await send_channel_message(channel, "⚠️ Fuel price update failed today (API/DNS connection issue).", delete_previous=True)
        return

    if not stations:
        await send_channel_message(channel, "No fuel data found in your current radius ⛽", delete_previous=True)
        return

    await send_channel_message(channel, build_report_message(stations), suppress_embeds=True, delete_previous=True)


@bot.command(name="setlocation")
async def set_location(ctx, *, place: str = ""):
    place = place.strip()
    if not place:
        await reply(ctx, "❌ Usage: `!setlocation <town/city/place>`")
        return

    try:
        found = geocode_location(place)
    except requests.RequestException:
        await reply(ctx, "⚠️ Location lookup failed right now. Please try again.")
        return

    if not found:
        await reply(ctx, "❌ Could not find that place. Try a clearer town/city name.")
        return

    settings = load_settings()
    settings["lat"] = found["lat"]
    settings["lon"] = found["lon"]
    settings["location_name"] = found["name"]
    save_settings(settings)
    await reply(
        ctx,
        "✅ Location updated:\n"
        f"`{found['name']}`\n"
        f"({found['lat']:.5f}, {found['lon']:.5f})"
    )


@bot.command(name="setradius")
async def set_radius(ctx, miles: str = ""):
    miles = miles.strip()
    if not miles:
        await reply(ctx, "❌ Usage: `!setradius <miles>`")
        return

    try:
        miles_value = float(miles)
    except ValueError:
        await reply(ctx, "❌ Radius must be a number. Example: `!setradius 12.5`")
        return

    if miles_value <= 0:
        await reply(ctx, "❌ Radius must be greater than 0.")
        return

    settings = load_settings()
    settings["radius_miles"] = miles_value
    save_settings(settings)
    await reply(ctx, f"✅ Radius set to `{miles_value:.1f}` miles")


@bot.command(name="fuelsettings")
async def fuel_settings(ctx):
    settings = load_settings()
    await reply(
        ctx,
        "⚙️ Current settings:\n"
        f"- Location: `{settings['lat']}, {settings['lon']}`\n"
        f"- Radius: `{settings['radius_miles']:.1f}` miles"
    )


@bot.command(name="fuelnow")
async def fuel_now(ctx):
    await reply(ctx, "Fetching fuel prices now...")
    try:
        stations = get_prices()
    except Exception as exc:
        await reply(ctx, f"⚠️ Fuel price fetch failed: {exc}")
        return

    if not stations:
        await reply(ctx, "No fuel data found in your current radius ⛽")
        return

    await reply(ctx, build_report_message(stations), suppress_embeds=True)


@bot.command(name="fetch")
async def fetch_now(ctx):
    await fuel_now(ctx)


@bot.command(name="petrol")
async def petrol_top(ctx):
    try:
        stations = get_prices()
    except Exception as exc:
        await reply(ctx, f"⚠️ Fuel price fetch failed: {exc}")
        return

    top = get_top_stations_by_fuel(stations, "petrol", limit=5)
    expires_at = time.time() + AUTO_DELETE_SECONDS if AUTO_DELETE_SECONDS > 0 else None
    PENDING_SELECTIONS_BY_USER[ctx.author.id] = {
        "fuel_label": "petrol (E10)",
        "stations": top,
        "created_at": time.time(),
        "expires_at": expires_at,
    }
    await reply(ctx, build_top5_message("petrol (E10)", "petrol", top), suppress_embeds=True)


@bot.command(name="e10")
async def e10_top(ctx):
    await petrol_top(ctx)


@bot.command(name="diesel")
async def diesel_top(ctx):
    try:
        stations = get_prices()
    except Exception as exc:
        await reply(ctx, f"⚠️ Fuel price fetch failed: {exc}")
        return

    top = get_top_stations_by_fuel(stations, "diesel", limit=5)
    expires_at = time.time() + AUTO_DELETE_SECONDS if AUTO_DELETE_SECONDS > 0 else None
    PENDING_SELECTIONS_BY_USER[ctx.author.id] = {
        "fuel_label": "diesel (B7)",
        "stations": top,
        "created_at": time.time(),
        "expires_at": expires_at,
    }
    await reply(ctx, build_top5_message("diesel (B7)", "diesel", top), suppress_embeds=True)


@bot.command(name="b7")
async def b7_top(ctx):
    await diesel_top(ctx)


@bot.command(name="super")
async def super_top(ctx):
    try:
        stations = get_prices()
    except Exception as exc:
        await reply(ctx, f"⚠️ Fuel price fetch failed: {exc}")
        return

    top = get_top_stations_by_fuel(stations, "super_unleaded", limit=5)
    expires_at = time.time() + AUTO_DELETE_SECONDS if AUTO_DELETE_SECONDS > 0 else None
    PENDING_SELECTIONS_BY_USER[ctx.author.id] = {
        "fuel_label": "super unleaded (E5)",
        "stations": top,
        "created_at": time.time(),
        "expires_at": expires_at,
    }
    await reply(ctx, build_top5_message("super unleaded (E5)", "super_unleaded", top), suppress_embeds=True)


@bot.command(name="e5")
async def e5_top(ctx):
    await super_top(ctx)


@bot.command(name="pick")
async def pick_station(ctx, number: str = ""):
    number = number.strip()
    if not number:
        await reply(ctx, "❌ Usage: `!pick <number>`")
        return

    try:
        index = int(number)
    except ValueError:
        await reply(ctx, "❌ Pick must be a number from 1 to 5.")
        return

    pending = PENDING_SELECTIONS_BY_USER.get(ctx.author.id)
    if not pending:
        await reply(ctx, "❌ No recent list found. Use `!petrol`/`!e10`, `!diesel`/`!b7`, or `!super`/`!e5` first.")
        return

    if time.time() - pending["created_at"] > SELECTION_TTL_SECONDS:
        PENDING_SELECTIONS_BY_USER.pop(ctx.author.id, None)
        await reply(ctx, "⌛ Your selection expired. Run `!petrol`/`!e10`, `!diesel`/`!b7`, or `!super`/`!e5` again.")
        return

    stations = pending["stations"]
    if not stations:
        await reply(ctx, "❌ No stations are available to pick from. Run the fuel command again.")
        return

    if index < 1 or index > len(stations):
        await reply(ctx, f"❌ Pick must be between 1 and {len(stations)}.")
        return

    station = stations[index - 1]
    expires_at = pending.get("expires_at")
    delete_after = None
    if expires_at is not None:
        delete_after = max(1, int(expires_at - time.time()))

    if DM_COMMAND_RESPONSES:
        try:
            dm_channel = await ctx.author.create_dm()
            await send_channel_message(
                dm_channel,
                (
                    f"🧭 **Route to option {index}** ({pending['fuel_label']})\n"
                    f"{station['name']}\n"
                    f"📍 <{station['maps_url']}>"
                ),
                suppress_embeds=True,
                delete_after=delete_after,
            )
            return
        except discord.Forbidden:
            pass

    await send_channel_message(
        ctx.channel,
        (
            f"🧭 **Route to option {index}** ({pending['fuel_label']})\n"
            f"{station['name']}\n"
            f"📍 <{station['maps_url']}>"
        ),
        suppress_embeds=True,
        delete_after=delete_after,
    )


@bot.command(name="commands")
async def list_commands(ctx):
    msg = (
        "📘 **Fuel Bot Commands**\n\n"
        "`!setlocation <town/city/place>` - Set your search location by name.\n"
        "`!setradius <miles>` - Set how far to search in miles.\n"
        "`!fuelsettings` - Show current location and search radius.\n"
        "`!fuelnow` - Fetch and show the latest fuel prices now.\n"
        "`!fetch` - Same as `!fuelnow` (manual refresh).\n"
        "`!petrol` - Show 5 cheapest petrol stations in range.\n"
        "`!e10` - Alias of `!petrol`.\n"
        "`!diesel` - Show 5 cheapest diesel stations in range.\n"
        "`!b7` - Alias of `!diesel`.\n"
        "`!super` - Show 5 cheapest super unleaded stations in range.\n"
        "`!e5` - Alias of `!super`.\n"
        "`!pick <number>` - Return Google Maps link for the selected station.\n"
        "`!commands` - Show this help list."
    )
    await reply(ctx, msg)


@bot.event
async def on_command_error(ctx, error):
    await cleanup_user_command(ctx)

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        cmd = ctx.command.name if ctx.command else ""
        if cmd == "setradius":
            await reply(ctx, "❌ Usage: `!setradius <miles>`")
        elif cmd == "setlocation":
            await reply(ctx, "❌ Usage: `!setlocation <town/city/place>`")
        elif cmd == "pick":
            await reply(ctx, "❌ Usage: `!pick <number>`")
        else:
            await reply(ctx, "❌ Missing required value. Try the command again with all arguments.")
        return

    if isinstance(error, commands.BadArgument):
        await reply(ctx, "❌ Invalid value type. Check your command format and try again.")
        return

    if isinstance(error, commands.CommandInvokeError):
        original = error.original
        await reply(ctx, f"⚠️ Command failed: {original}")
        return

    await reply(ctx, "⚠️ An unexpected command error occurred. Please try again.")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not daily_post.is_running():
        daily_post.start()


bot.run(TOKEN)