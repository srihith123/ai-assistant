#!/Users/ansh_is_g/.pyenv/versions/3.11.5/bin/python3
"""
## AI Math and English Tutor (Native Host)
Receives screenshot data from the Chrome extension via Native Messaging,
and uses Gemini's real-time API to provide interactive audio tutoring.

Based on Gemini LiveAPI Quickstart: https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_LiveAPI.py

## Setup
Install dependencies: pip install google-genai pyaudio pillow python-dotenv
Create .env file: GOOGLE_API_KEY=YOUR_API_KEY_HERE
Register native host manifest (see documentation).
"""

import asyncio
import base64
import io
import traceback
import os
import sys
import json
import logging
import struct # For native messaging length prefix
from dotenv import load_dotenv

import pyaudio
import PIL.Image
from google import genai
from google.genai import types

# --- Native Messaging Helpers ---\n

# Configure logging to a file for debugging native host
log_file_path = os.path.join(os.path.expanduser("~"), "ai_tutor_native_host.log")
logging.basicConfig(level=logging.INFO,
                    filename=log_file_path,
                    filemode='w', # Overwrite log on each start
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Function to read a message from standard input
def read_native_message():
    try:
        text_length_bytes = sys.stdin.buffer.read(4)
        if not text_length_bytes:
            logger.info("No more data from stdin, exiting read loop.")
            return None # End of stream
        text_length = struct.unpack('@I', text_length_bytes)[0]
        message_bytes = sys.stdin.buffer.read(text_length)
        message_json = message_bytes.decode('utf-8')
        message = json.loads(message_json)
        logger.info(f"Received message: Type={message.get('type', 'N/A')}, Length={text_length}")
        return message
    except struct.error as e:
        logger.error(f"Error unpacking message length: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON message: {e} - Received: {message_bytes.decode('utf-8', errors='ignore')}")
        return None
    except Exception as e:
         logger.error(f"Unexpected error reading native message: {e}", exc_info=True)
         return None

# Function to send a message to standard output (optional for now)
def send_native_message(message):
    try:
        message_json = json.dumps(message).encode('utf-8')
        message_length = len(message_json)
        sys.stdout.buffer.write(struct.pack('@I', message_length))
        sys.stdout.buffer.write(message_json)
        sys.stdout.buffer.flush()
        logger.info(f"Sent message: {message}")
    except Exception as e:
         logger.error(f"Error sending native message: {e}", exc_info=True)

# --- End Native Messaging Helpers ---\n


# Load environment variables (for API key)
load_dotenv()

# Settings
API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "models/gemini-2.0-flash-live-001"

# Audio settings
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

# Define a system prompt for tutoring
TUTOR_PROMPT = """
You are an AI tutor specializing in mathematics and English based on the provided screenshot. Your goal is to:
1. Analyze the problem in the screenshot.
2. Guide the student through the solution step-by-step using audio.
3. Explain concepts clearly using examples related to the problem.
4. Answer follow-up questions patiently.
5. Maintain a supportive and encouraging tone.
6. Once you are initialized with the image, immediately start helping the user with the problem shown in the screenshot.

Start by analyzing the image and providing an initial audio explanation based on the TUTOR_PROMPT and the image content.
"""

# Configuration for the Live API
LIVE_CONFIG = types.LiveConnectConfig(
    response_modalities=["audio"],
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
        )
    ),
)

class GeminiTutorNativeHost:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key is required.")
        self.api_key = api_key
        self.pya = pyaudio.PyAudio()
        self.session = None
        self.audio_in_queue = asyncio.Queue() # Incoming audio from Gemini
        self.out_queue = asyncio.Queue(maxsize=20) # Outgoing audio/image to Gemini
        self.initial_image_sent = False
        self.current_image_data = None # Store received image data
        self.gemini_task_group = None # To manage Gemini interaction tasks
        
        self.client = genai.Client(http_options={"api_version": "v1alpha"}, api_key=self.api_key)
        logger.info("Gemini tutor native host initialized successfully")

    def _prepare_image_from_data_url(self, data_url):
        """Decode base64 data URL and prepare image part for API."""
        try:
            if not data_url.startswith('data:image/'):
                logger.error("Invalid image data URL format.")
                return None

            header, encoded = data_url.split(',', 1)
            mime_type = header.split(';')[0].split(':')[1]
            image_bytes = base64.b64decode(encoded)
            logger.info(f"Image decoded successfully ({len(image_bytes)} bytes, {mime_type})")
            
            # Verify image data (optional but recommended)
            try:
                 img = PIL.Image.open(io.BytesIO(image_bytes))
                 img.verify() # Verify image header
                 logger.info(f"Image verified: format={img.format}")
            except Exception as img_err:
                 logger.error(f"Image verification failed: {img_err}")
                 # Decide if you want to proceed anyway or return None
                 return None

            # API expects base64 string in the dict
            return {"mime_type": mime_type, "data": encoded}
        except Exception as e:
            logger.error(f"Error processing image data URL: {e}", exc_info=True)
            return None

    async def start_gemini_session(self): # Renamed from process_image
        """Connects to Gemini and queues initial image/prompt if available."""
        if not self.current_image_data:
            logger.error("Cannot start Gemini session: No image data received yet.")
            return
        if self.initial_image_sent:
             logger.info("Gemini session already started for the current image.")
             return
            
        prepared_image_part = self._prepare_image_from_data_url(self.current_image_data)
        if not prepared_image_part:
             logger.error("Failed to prepare image data for Gemini.")
             # Notify extension?
             return
            
        try:
            logger.info("Starting Gemini session and sending initial data...")
            # Use the client from __init__
            async with self.client.aio.live.connect(model=MODEL_NAME, config=LIVE_CONFIG) as session:
                self.session = session
                logger.info("Live API session connected successfully.")
                
                # Put initial prompt and image into the queue
                await self.out_queue.put(TUTOR_PROMPT)
                await self.out_queue.put(prepared_image_part)
                await self.out_queue.put(
                    "Please analyze the image and start guiding me via audio."
                )
                self.initial_image_sent = True
                logger.info("Initial image and prompt queued for sending.")
                
                # Keep session alive by running send/receive loops
                # Run tasks within this session context
                async with asyncio.TaskGroup() as tg:
                     self.gemini_task_group = tg
                     logger.info("Starting Gemini communication tasks...")
                     # Don't start send_text here, controlled by main loop
                     tg.create_task(self.send_realtime(), name="SendRealtime")
                     tg.create_task(self.listen_audio(), name="ListenAudio")
                     tg.create_task(self.receive_audio(), name="ReceiveAudio")
                     tg.create_task(self.play_audio(), name="PlayAudio")
                     # Wait indefinitely until cancelled or an error occurs
                     await asyncio.sleep(3600 * 24) # Keep running

        except asyncio.CancelledError:
             logger.info("Gemini session task cancelled.")
        except Exception as e:
            logger.error(f"Error during Gemini session: {e}", exc_info=True)
            self.session = None # Ensure session is marked as closed
            self.initial_image_sent = False
        finally:
             logger.info("Gemini session attempt finished.")
             self.session = None # Ensure session is cleared on exit
             self.initial_image_sent = False
             if self.gemini_task_group:
                 # Attempt cancellation if group still exists
                 # Usually TaskGroup handles this on exit
                 pass
                
    # send_text, listen_audio, receive_audio, play_audio, send_realtime remain largely the same
    # Minor changes: Check self.session before using it
    async def send_text(self): # Removed as text input comes via native messaging now
        pass

    async def send_realtime(self):
        """Sends data (audio/image) from the out_queue via session.send."""
        while True:
            try:
                if not self.session:
                    await asyncio.sleep(0.1)
                    continue
                msg = await self.out_queue.get()
                if msg is None: 
                     logger.info("Received stop signal for send_realtime.")
                     break
                logger.debug(f"Sending message type: {type(msg)}")
                await self.session.send(input=msg)
                self.out_queue.task_done()
            except asyncio.CancelledError:
                logger.info("Send realtime task cancelled.")
                break
            except Exception as e:
                 logger.error(f"Error in send_realtime: {e}", exc_info=True)
                 await asyncio.sleep(0.1)
        logger.info("Send realtime task finished.")

    async def listen_audio(self):
        """Capture audio from the microphone and put it into out_queue."""
        audio_stream = None
        try:
            mic_info = self.pya.get_default_input_device_info()
            logger.info(f"Using microphone: {mic_info['name']}")
            audio_stream = await asyncio.to_thread(
                self.pya.open, format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
                input=True, input_device_index=mic_info["index"], frames_per_buffer=CHUNK_SIZE
            )
            logger.info("Microphone stream opened. Listening...")
            while True:
                try:
                    if not self.session:
                         await asyncio.sleep(0.1) 
                         continue
                    data = await asyncio.to_thread(audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)
                    await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
                except OSError as e:
                     logger.warning(f"Error reading from audio stream (likely harmless overflow): {e}")
                     await asyncio.sleep(0.01) 
                except Exception as e:
                     logger.error(f"Unexpected error in listen_audio loop: {e}", exc_info=True)
                     break 
        except asyncio.CancelledError:
            logger.info("Listen audio task cancelled.")
        except Exception as e:
             logger.error(f"Failed to open or initialize microphone stream: {e}", exc_info=True)
             # Don't raise CancelledError here, let main loop handle exit
        finally:
            if audio_stream:
                logger.info("Closing microphone stream in listen_audio.")
                try:
                    await asyncio.to_thread(audio_stream.stop_stream)
                    await asyncio.to_thread(audio_stream.close)
                except Exception as e:
                    logger.error(f"Error closing audio stream: {e}") 
        logger.info("Listen audio task finished.")
                
    async def receive_audio(self):
        """Receive responses from the model via session.receive and queue audio."""
        logger.info("Starting to receive responses...")
        while True:
            try:
                if not self.session:
                    logger.warning("Receive loop: Session not ready, waiting...")
                    await asyncio.sleep(1)
                    continue
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data: 
                        logger.debug(f"Received audio chunk: {len(data)} bytes")
                        self.audio_in_queue.put_nowait(data)
                    if text := response.text: 
                        # Log text for debugging, don't print to stdout
                        logger.info(f"[AI Tutor]: {text.strip()}") 
                    if hasattr(response, 'error') and response.error:
                        logger.error(f"Received error from API in response: {response.error}")
            except asyncio.CancelledError:
                logger.info("Receive audio task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error receiving responses: {e}", exc_info=True)
                break
        logger.info("Receive audio task finished.")
               
    async def play_audio(self):
        """Play audio received from the model via audio_in_queue."""
        stream = None
        try:
            logger.info("Initializing audio playback stream...")
            stream = await asyncio.to_thread(
                self.pya.open, format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True
            )
            logger.info("Audio playback stream opened.")
            while True:
                try:
                    bytestream = await self.audio_in_queue.get()
                    if bytestream is None: 
                        logger.info("Received stop signal for audio playback.")
                        self.audio_in_queue.task_done()
                        break 
                    logger.debug(f"Playing audio chunk: {len(bytestream)} bytes")
                    await asyncio.to_thread(stream.write, bytestream)
                    self.audio_in_queue.task_done() 
                except asyncio.CancelledError:
                     logger.info("Play audio task cancelled inside loop.")
                     break # Exit loop if cancelled while waiting/playing
        except asyncio.CancelledError:
             logger.info("Play audio task cancelled.")
        except Exception as e:
            logger.error(f"Error in play_audio: {e}", exc_info=True)
        finally:
            if stream:
                logger.info("Closing audio playback stream.")
                try:
                    await asyncio.to_thread(stream.stop_stream)
                    await asyncio.to_thread(stream.close)
                except Exception as e:
                    logger.error(f"Error closing playback stream: {e}")
            logger.info("Play audio task finished.")
                    
    async def main_loop(self):
        """Main loop to read native messages and manage Gemini session."""
        logger.info("Starting native host main loop.")
        gemini_session_task = None
        try:
            while True:
                message = await asyncio.to_thread(read_native_message)
                if message is None:
                    logger.info("Exiting main loop: No more messages from Chrome.")
                    break # End of input stream

                if message.get("type") == "image_data":
                    logger.info("Received image data from extension.")
                    received_image_data = message.get("imageData")
                    if received_image_data:
                        # If there's an existing session, cancel it first
                        if gemini_session_task and not gemini_session_task.done():
                            logger.info("Cancelling existing Gemini session for new image...")
                            gemini_session_task.cancel()
                            try:
                                 await gemini_session_task # Wait for cancellation
                            except asyncio.CancelledError:
                                 logger.info("Previous session cancelled.")
                            except Exception as e:
                                 logger.error(f"Error awaiting previous session cancellation: {e}")
                            self.session = None # Ensure session is cleared
                            self.initial_image_sent = False
                            # Clear queues?
                            while not self.out_queue.empty(): self.out_queue.get_nowait()
                            while not self.audio_in_queue.empty(): self.audio_in_queue.get_nowait()
                           
                        self.current_image_data = received_image_data
                        self.initial_image_sent = False # Reset for new image
                        # Launch the Gemini session task
                        logger.info("Creating new Gemini session task...")
                        gemini_session_task = asyncio.create_task(self.start_gemini_session(), name="GeminiSession")
                    else:
                        logger.warning("Received image_data message with no imageData field.")
               
                # Handle other message types from extension if needed
                # elif message.get("type") == "user_text":
                #    if self.session:
                #        await self.session.send(input=message.get("text", ""), end_of_turn=True)
                #    else:
                #        logger.warning("Received user text but no active Gemini session.")
                       
                else:
                    logger.warning(f"Received unknown message type: {message.get('type')}")
                   
        except asyncio.CancelledError:
            logger.info("Main loop cancelled externally.")
        except Exception as e:
             logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            logger.info("Main loop finished. Cleaning up...")
            if gemini_session_task and not gemini_session_task.done():
                logger.info("Cancelling active Gemini session task on exit...")
                gemini_session_task.cancel()
                try:
                    await gemini_session_task
                except asyncio.CancelledError:
                    pass # Expected
                except Exception as e:
                     logger.error(f"Error awaiting final session cancellation: {e}")
            
            # Ensure PyAudio terminates *after* tasks using it are likely stopped
            if self.pya:
                logger.info("Terminating PyAudio in main loop finally.")
                # Add a small delay to ensure audio tasks might have reacted to cancellation/stop signals
                await asyncio.sleep(0.2)
                await asyncio.to_thread(self.pya.terminate)
                
            logger.info("Native host cleanup complete.")

# --- Main Execution --- 
if __name__ == "__main__":
    logger.info("Starting AI Tutor Native Host Script.")
    # Remove argument parsing
    
    api_key_to_use = API_KEY 
    if not api_key_to_use:
        logger.critical("Google API Key not found in environment variables (GOOGLE_API_KEY).")
        sys.exit(1)

    try:
        # Pass only API key, image comes via native message
        host = GeminiTutorNativeHost(api_key=api_key_to_use)
        asyncio.run(host.main_loop())
    except ValueError as e:
         logger.critical(f"Initialization Error: {e}")
         sys.exit(1)
    except KeyboardInterrupt:
         logger.info("Exiting due to KeyboardInterrupt...")
    except Exception as e:
         logger.critical(f"An unexpected error occurred at top level:", exc_info=True)
    finally:
         logger.info("Native Host Application finished.") 