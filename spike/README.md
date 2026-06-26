# Spike: Pipeline Validation (Telegram → YandexGPT → Telegram)

This spike validates that the Telegram → YandexGPT → Telegram pipeline works correctly before starting main application development.

## Manual Test Instructions

### Setup

1. Copy `.env.example` from project root to `.env`:
   ```bash
   cp ../.env.example ../.env
   ```

2. Fill in your credentials in `../.env`:
   - `TELEGRAM_TOKEN`: Your Telegram bot token
   - `YANDEX_API_KEY`: Your Yandex Cloud API key
   - `YANDEX_FOLDER_ID`: Your Yandex Cloud folder ID

3. Install dependencies:
   ```bash
   pip install aiogram httpx python-dotenv
   ```

4. Run the bot:
   ```bash
   python bot_spike.py
   ```

### Test Scenarios

#### Step 3: Test Text Processing
Send the following text to your bot:
```
Лукойл на Ленинском, АИ-95 есть по 79 руб
```

Expected result: Bot responds with JSON containing extracted gas station name, fuel grades, availability, and price.

#### Step 4: Test Photo Processing
Send a photo of a gas price board/display to the bot.

Expected result: Bot responds with JSON containing extracted gas station name, fuel grades, and prices from the image.

#### Step 5: Test Voice Processing
Send a voice message to the bot with information about fuel availability.

Expected result: Bot transcribes the voice message, then responds with JSON containing extracted station info, fuel types, availability, and price.

### Expected Output Format

For all three scenarios, expect JSON responses like:
```json
{
  "station_name": "Лукойл",
  "location": "Ленинский",
  "fuel_grades": ["АИ-95"],
  "availability": "есть",
  "price": 79
}
```

### Result Status

After running all three test scenarios, record whether the spike works:
- ✅ Working
- ⚠️ Partially working
- ❌ Not working

If there are issues, debug by checking:
1. API key validity (YandexGPT)
2. Folder ID validity (YandexGPT)
3. Speech recognition language/format settings
4. Network connectivity and timeouts
5. Telegram token validity

### Cleanup

After spike validation, this directory can be deleted. The spike is throwaway code not included in the main application.
