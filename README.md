# Textractor → SillyTavern Bridge

Listens for input from Textractor WebSocket hook as a client and sends it to SillyTavern as `/send` commands. You will need to have [Textractor](https://github.com/Artikash/Textractor) installed together with [textractor_websocket](https://github.com/kuroahna/textractor_websocket/) plugin. You will need to have python installed on your machine to run the script.

## Setup
1. Create a folder where you want to have the tool
2. Open admin CMD and cd to the created folder
3. Run 'git clone https://github.com/amaenb0u/Textractor-to-SillyTavern/' via git
4. Run `install.cmd` to create Python env and install deps
5. Start **Chromium with remote debugging**:
   ```
   %LocalAppData%\ms-playwright\chromium-*/chrome-win64\chrome.exe --remote-debugging-port=9222
   ```
6. Open SillyTavern in this Chrome (`http://localhost:8000`)
7. Start Textractor, attach it to the game and configure text extraction
8. Run `start.cmd`

## Customization
Edit `textractor_raw_bridge.py`:
- `TEXTRACTOR_HOST/PORT`: WebSocket endpoint (default: localhost:6677)
- `CHROME_DEBUGGING_URL`: Chrome debug port (default: http://localhost:9222)
- `SILLYTAVERN_URL`: SillyTavern address (default: http://localhost:8000)
- `TEXT_FORMAT`: "bracket", "prefix", "quote", "none"
