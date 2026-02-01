import socket
import asyncio
import base64
import logging
import signal
from playwright.async_api import async_playwright

# ==================== CONFIGURATION ====================
TEXTRACTOR_HOST = 'localhost'
TEXTRACTOR_PORT = 6677
CHROME_DEBUGGING_URL = "http://localhost:9222"
SILLYTAVERN_URL = "http://localhost:8000"
TEXT_FORMAT = "bracket"  # Options: "bracket", "prefix", "quote", "none"
# ======================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class RawWebSocketClient:
    """A minimal WebSocket client using raw sockets."""
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.buffer = bytearray()
        
    def connect(self):
        """Establish a raw WebSocket connection with the exact handshake."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            
            # Generate a NEW, random WebSocket Key for this handshake
            import random
            import string
            key = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            ws_key = base64.b64encode(key.encode()).decode()
            
            # Craft the EXACT handshake request
            handshake = (
                f"GET / HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0\r\n"
                f"Accept: */*\r\n"
                f"Accept-Language: en-US,en;q=0.5\r\n"
                f"Accept-Encoding: gzip, deflate, br, zstd\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"Origin: null\r\n"
                f"Sec-WebSocket-Extensions: permessage-deflate\r\n"
                f"Sec-WebSocket-Key: {ws_key}\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-Fetch-Dest: empty\r\n"
                f"Sec-Fetch-Mode: websocket\r\n"
                f"Sec-Fetch-Site: cross-site\r\n"
                f"Pragma: no-cache\r\n"
                f"Cache-Control: no-cache\r\n"
                f"Upgrade: websocket\r\n"
                f"\r\n"
            )
            
            logger.info("📤 Sending WebSocket handshake...")
            self.sock.send(handshake.encode())
            
            # Read the response
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Server closed connection during handshake")
                response += chunk
            
            resp_text = response.decode('utf-8', errors='ignore')
            if "101 Switching Protocols" in resp_text:
                logger.info("✅ WebSocket handshake successful!")
                # Set a short timeout for non-blocking receives in the main loop
                self.sock.settimeout(0.1)
                return True
            else:
                logger.error(f"❌ Handshake failed. Response:\n{resp_text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            if self.sock:
                self.sock.close()
            return False
    
    def receive_message(self):
        """Read a single text frame from the WebSocket."""
        if not self.sock:
            return None
            
        try:
            # Read the frame header (minimal implementation)
            header = self.sock.recv(2)
            if not header or len(header) < 2:
                return None
                
            # Parse simple text frame (OPCODE 1)
            first_byte, second_byte = header[0], header[1]
            
            # Check if this is a text frame and not masked
            if (first_byte & 0x0F) != 0x01:
                # Skip this frame
                length = second_byte & 0x7F
                if length == 126:
                    self.sock.recv(2)
                elif length == 127:
                    self.sock.recv(8)
                self.sock.recv(length)
                return self.receive_message()
            
            # Get payload length
            payload_len = second_byte & 0x7F
            
            if payload_len == 126:
                len_bytes = self.sock.recv(2)
                payload_len = int.from_bytes(len_bytes, byteorder='big')
            elif payload_len == 127:
                len_bytes = self.sock.recv(8)
                payload_len = int.from_bytes(len_bytes, byteorder='big')
            
            # Read the payload
            payload = self.sock.recv(payload_len)
            return payload.decode('utf-8', errors='replace')
            
        except socket.timeout:
            return None
        except Exception as e:
            logger.error(f"❌ Error receiving message: {e}")
            return None
    
    def close(self):
        """Close the connection with proper WebSocket close frame."""
        if self.sock:
            try:
                # WebSocket close frame must be masked when sent from client
                # Close frame: FIN=1, opcode=0x8, MASK=1, payload_len=2 (status code)
                # Status code 1000 = normal closure
                import os
                mask_key = os.urandom(4)
                status_code = b'\x03\xe8'  # 1000 in big-endian
                
                # Apply mask to payload
                masked_payload = bytes([status_code[i] ^ mask_key[i % 4] for i in range(2)])
                
                # Build close frame: 0x88 = FIN + opcode 8, 0x82 = MASK + length 2
                close_frame = b'\x88\x82' + mask_key + masked_payload
                
                self.sock.settimeout(2.0)
                self.sock.send(close_frame)
                
                # Wait for server's close frame response
                try:
                    response = self.sock.recv(128)
                    logger.debug(f"Received close response: {len(response)} bytes")
                except socket.timeout:
                    logger.debug("Timeout waiting for close response")
                except:
                    pass
                    
            except Exception as e:
                logger.debug(f"Error during close: {e}")
            finally:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                self.sock.close()
                self.sock = None

class SillyTavernBridge:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
        self.ws_client = None
        self.last_text = ""
        self.should_exit = False
        self.format_style = TEXT_FORMAT
        
        self.text_queue = asyncio.Queue()
        
    async def check_ai_responding(self):
        """Check if AI is currently generating a response."""
        try:
            is_responding = await self.page.evaluate("""
                () => {
                    const mesStop = document.getElementById('mes_stop');
                    if (mesStop) {
                        const style = window.getComputedStyle(mesStop);
                        if (style.display !== 'none') return true;
                    }
                    return false;
                }
            """)
            return bool(is_responding)
        except:
            return False
    
    async def _send_immediate(self, processed_text):
        """Immediate send without queue checks - fast method using direct DOM manipulation."""
        try:
            # Use fill() and keyboard for fastest possible input
            textarea = await self.page.query_selector("#send_textarea")
            if textarea:
                # Clear and fill directly - fastest method
                await textarea.fill(f"/send {processed_text}")
                await textarea.press("Enter")
                logger.info(f"📤 Sent to ST: {processed_text[:60]}...")
            else:
                logger.error("❌ Could not find send_textarea")
        except Exception as e:
            logger.error(f"❌ Failed to send to ST: {e}")
    
    async def process_queue_once(self):
        """Process queued text if AI not responding."""
        if self.text_queue.empty():
            return
        
        # Check if AI is responding before processing
        if await self.check_ai_responding():
            return
        
        try:
            processed_text = self.text_queue.get_nowait()
            await self._send_immediate(processed_text)
        except asyncio.QueueEmpty:
            pass
        
    def format_text(self, text):
        """Format game text before sending to SillyTavern with minimal tokens."""
        if self.format_style == "bracket":
            return f"[Game]: {text}"
        elif self.format_style == "prefix":
            return f"> {text}"
        elif self.format_style == "quote":
            return f"\"{text}\""
        else:
            return text
    
    async def connect_to_browser(self):
        """Connect to Chrome with remote debugging."""
        try:
            logger.info("🔗 Connecting to Chrome...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.connect_over_cdp(CHROME_DEBUGGING_URL)
            
            # Find SillyTavern
            context = self.browser.contexts[0]
            for pg in context.pages:
                title = await pg.title()
                if "sillytavern" in title.lower():
                    self.page = pg
                    logger.info(f"✅ Found SillyTavern: {title}")
                    break
            
            if not self.page:
                logger.info("📄 Opening new SillyTavern tab...")
                self.page = await context.new_page()
                await self.page.goto(SILLYTAVERN_URL)
                await self.page.wait_for_load_state("networkidle")
            
            return True
        except Exception as e:
            logger.error(f"❌ Browser connection failed: {e}")
            return False
    
    async def send_to_sillytavern(self, text):
        """Send text to SillyTavern with queue management."""
        if not text or text.strip() == "" or text == self.last_text:
            return
        
        self.last_text = text
        processed_text = self.format_text(text)
        
        is_responding = await self.check_ai_responding()
        if is_responding:
            await self.text_queue.put(processed_text)
            logger.info(f"⏳ AI responding, queued: {processed_text[:60]}...")
        else:
            # First drain any queued messages
            await self.process_queue_once()
            await self._send_immediate(processed_text)
    
    async def run(self):
        """Main bridge loop with clean shutdown handling."""
        # Setup signal handler for Ctrl+C
        def signal_handler(signum, frame):
            logger.info("\n🛑 Shutdown signal received. Closing gracefully...")
            self.should_exit = True
        
        signal.signal(signal.SIGINT, signal_handler)
        
        # Connect to browser
        if not await self.connect_to_browser():
            return
        
        # Connect to Textractor with raw socket
        logger.info(f"🌐 Connecting to ws://{TEXTRACTOR_HOST}:{TEXTRACTOR_PORT}")
        self.ws_client = RawWebSocketClient(TEXTRACTOR_HOST, TEXTRACTOR_PORT)
        
        if not self.ws_client.connect():
            logger.error("❌ Failed to connect to Textractor")
            return
        
        logger.info("🚀 Bridge is running! Processing text...")
        logger.info("   Text format: " + self.format_style)
        logger.info("   Press Ctrl+C to stop cleanly.")
        
        # Main receive loop with exit flag check
        try:
            while not self.should_exit:
                message = self.ws_client.receive_message()
                if message:
                    logger.info(f"📨 From game: {message[:80]}...")
                    await self.send_to_sillytavern(message.strip())
                
                # Periodically process queue even if no new message
                await self.process_queue_once()
                
                # Small sleep to prevent CPU spinning
                await asyncio.sleep(0.05)
                
        except KeyboardInterrupt:
            logger.info("🛑 Keyboard interrupt received.")
        except Exception as e:
            logger.error(f"🔥 Bridge error: {e}")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Orderly cleanup to prevent Textractor crashes."""
        logger.info("🧹 Starting cleanup...")
        
        # 1. Close WebSocket connection properly
        if self.ws_client:
            self.ws_client.close()
            logger.debug("Closed WebSocket client")
        
        # 2. Close browser connection
        if self.browser:
            await self.browser.close()
            logger.debug("Closed browser")
        
        # 3. Stop Playwright
        if self.playwright:
            await self.playwright.stop()
            logger.debug("Stopped Playwright")
        
        logger.info("👋 Cleanup complete. Safe to restart.")
    
    async def close(self):
        """Cleanup alias for backward compatibility."""
        await self.cleanup()

async def main():
    bridge = SillyTavernBridge()
    try:
        await bridge.run()
    finally:
        if not bridge.should_exit:
            await bridge.close()

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("    Textractor → SillyTavern Bridge")
    logger.info("=" * 50)
    asyncio.run(main())