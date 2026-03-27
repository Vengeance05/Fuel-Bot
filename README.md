# ⛽ Fuel Price Discord Bot

A Discord bot that finds and displays the cheapest fuel prices near you in real-time. Supports E10 (Petrol), E5 (Super Unleaded), and B7 (Diesel) with interactive slash commands and location-based filtering.

## ✨ Features

- **Interactive `/fuel` GUI** - Slash command with fuel type buttons and settings modals
- **Real-time Price Data** - Fetches current fuel prices from Asda, Tesco, and Morrisons
- **Location-Based Filtering** - Search by town/city name with configurable radius
- **Google Maps Integration** - Direct links to each station for navigation
- **Ephemeral Responses** - Private messages that only you can see
- **Settings Management** - Change location and search radius on-the-fly
- **Prefix Commands** - Legacy `!petrol`, `!diesel`, etc. for backwards compatibility
- **Graceful Error Handling** - Fallback feeds if primary APIs unavailable

## 📋 Requirements

- Python 3.11+
- discord.py 2.0+
- requests
- python-dotenv

## 🚀 Setup

### 1. Install Dependencies

```bash
pip install discord.py requests python-dotenv
```

### 2. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Go to "Bot" tab → "Add Bot"
4. Copy the token
5. Under "OAuth2" → "URL Generator":
   - Select scopes: `bot`, `applications.commands`
   - Select permissions: `Send Messages`, `Embed Links`
   - Copy and visit the generated URL to add bot to your server

### 3. Configure `.env` File

Create a `.env` file in the bot directory:

```env
DISCORD_TOKEN=your_bot_token_here

# Optional: DM responses (default: false)
BOT_DM_RESPONSES=false

# Optional: Delete bot messages after N seconds (0 = never delete)
BOT_DELETE_AFTER_SECONDS=60

# Optional: Delete user command messages (default: false)
BOT_DELETE_USER_COMMAND_MESSAGES=false
```

### 4. Run the Bot

```bash
python "import discord.py"
```

## 📖 Commands

### Slash Commands (Recommended)

#### `/fuel`
Interactive fuel price selector with location and radius display.
- Shows your current search location and radius
- Buttons to select fuel type (E10, E5, B7)
- Buttons to change location and radius
- Displays top 5 cheapest stations with dropdown picker
- **Usage**: `/fuel`

#### `/setlocation`
Change your search location.
- **Usage**: `/setlocation <town/city>`
- **Example**: `/setlocation Derby`

#### `/setradius`
Change your search radius in miles.
- **Usage**: `/setradius <miles>`
- **Example**: `/setradius 15`

#### `/fuelsettings`
View your current location and radius settings.
- **Usage**: `/fuelsettings`

### Prefix Commands (Legacy)

All prefix commands use the `!` prefix:

| Command | Description |
|---------|-------------|
| `!petrol` | Get cheapest E10 petrol stations |
| `!diesel` | Get cheapest B7 diesel stations |
| `!super` | Get cheapest E5 super unleaded stations |
| `!e10` | Alias for `!petrol` |
| `!e5` | Alias for `!super` |
| `!b7` | Alias for `!diesel` |
| `!pick <number>` | Select a station from the last list |
| `!commands` | Show all available commands |
| `!setlocation <place>` | Change location (same as slash command) |
| `!setradius <miles>` | Change radius (same as slash command) |
| `!fuelsettings` | View current settings |

## 🎮 Usage Examples

### Finding Fuel

1. **Open the interactive selector:**
   ```
   /fuel
   ```
   - Bot shows your location and radius
   - Click a fuel type button (E10, E5, B7)
   - Select a station from the dropdown
   - Bot sends you a private message with the station name and Google Maps link

2. **Change Location:**
   - Click "📍 Change Location" button in `/fuel` menu
   - Enter town/city name in the modal
   - Bot geocodes it and updates your settings

3. **Change Radius:**
   - Click "📋 Change Radius" button in `/fuel` menu
   - Enter radius in miles
   - Bot updates your settings

## ⚙️ Configuration

### Environment Variables

- **DISCORD_TOKEN** (Required) - Your Discord bot token
- **BOT_DM_RESPONSES** (Optional) - Send responses as DMs (`true`/`false`, default: `false`)
- **BOT_DELETE_AFTER_SECONDS** (Optional) - Auto-delete bot messages (0 = never, default: `60`)
- **BOT_DELETE_USER_COMMAND_MESSAGES** (Optional) - Delete user's command messages (`true`/`false`, default: `false`)

### Settings File

Bot settings are saved to `fuel_settings.json`:

```json
{
  "location_name": "Derby",
  "lat": 52.9249,
  "lon": -1.4758,
  "radius_miles": 10.0
}
```

This file is automatically created and managed by the bot.

## 🔍 How It Works

1. **Geocoding** - Uses OpenStreetMap Nominatim API to convert town names to coordinates
2. **Price Fetching** - Queries public fuel price feeds from major UK retailers
3. **Distance Calculation** - Uses Haversine formula to filter stations by radius
4. **Sorting** - Returns top 5 cheapest stations by fuel type
5. **Maps Integration** - Generates Google Maps links for easy navigation

### Data Sources

- **Asda** - Real-time fuel price feed
- **Tesco** - Fuel pricing API
- **Morrisons** - Fuel station data
- **Fallback Chain** - If one fails, bot tries the next automatically

## 🛠️ Troubleshooting

### Bot Not Responding

**Problem:** Bot doesn't reply to commands.

**Solutions:**
1. Verify bot is in your server (check member list)
2. Check bot permissions in channel (View Channel, Send Messages, Embed Links)
3. Verify `DISCORD_TOKEN` in `.env` is correct
4. Restart bot: `python "import discord.py"`

### "Missing Access" Error on Startup

**Problem:** Deprecated code trying to access a specific channel.

**Solution:** This has been removed. Bot now works from any channel. Delete old `CHANNEL_ID` from `.env` if present.

### Location Not Found

**Problem:** Geocoding fails with "Could not find that place."

**Solutions:**
1. Try a more specific location (e.g., "Derby, UK" instead of "Derby")
2. Use nearby larger city name
3. Check OpenStreetMap for the exact name

### No Fuel Prices Found

**Problem:** "No fuel data found in your radius."

**Solutions:**
1. Increase your search radius (`/setradius 20`)
2. Try a different location
3. Check if fuel data APIs are available

### Price Data Is Old

**Problem:** Prices haven't updated.

**Solution:** Bot fetches fresh data on each `/fuel` call. Prices update on their own schedule from retailers (typically hourly).

## 📁 Project Structure

```
BOT/
├── import discord.py        # Main bot file (all commands and logic)
├── .env                     # Configuration (create this)
├── fuel_settings.json       # User settings (auto-generated)
└── README.md               # This file
```

## 🔐 Security Notes

- **Never commit `.env` to version control**
- **Bot token in `.env` is private** - don't share it
- **Messages are ephemeral** - only visible to command user by default
- **No data is stored** - only local settings JSON

## 🐛 Known Issues

- Nominatim API may rate-limit if too many geocoding requests
- Fuel prices may be 1-2 hours delayed from actual pump prices
- Some small/independent fuel stations may not be in the feeds

## 📝 License

Free to use and modify for personal/community Discord servers.

## 💬 Support

For issues or feature requests, check:
1. Your bot token is valid
2. Bot has necessary permissions
3. Python 3.11+ is installed
4. All dependencies are up to date: `pip install -U discord.py requests python-dotenv`

---

**Built with discord.py** | Fuel data from public UK retailers
