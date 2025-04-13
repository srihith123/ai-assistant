"""
## AI Math and English Tutor (Real-time Audio Test)
This application processes images containing math or English problems and aims to use Gemini's 
real-time API to provide interactive audio tutoring.

Based on Gemini LiveAPI Quickstart: https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_LiveAPI.py

## Setup
To install the dependencies for this script, run:

```
pip install google-genai pyaudio pillow python-dotenv
```

Create a .env file in the same directory with your API key:
GOOGLE_API_KEY=YOUR_API_KEY_HERE
"""

import asyncio
import base64
import io
import traceback
import os
import sys
import json
import logging
import argparse
from dotenv import load_dotenv

import pyaudio
import PIL.Image
from google import genai
from google.genai import types # Import types for config

# Load environment variables (for API key)
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Settings
API_KEY = os.getenv("GOOGLE_API_KEY")
# Use the model name from the working example
MODEL_NAME = "models/gemini-2.0-flash-live-001" 
DEFAULT_IMAGE_PATH = None

# Audio settings (Match working example where possible)
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000 # Rate for microphone input
RECEIVE_SAMPLE_RATE = 24000 # Rate expected for audio output from model
CHUNK_SIZE = 1024

# Define a system prompt for tutoring
TUTOR_PROMPT = """
You are an AI tutor specializing in mathematics and English. Your goal is to:
1. Analyze the image containing a math or English problem.
2. Guide the student through the solution step-by-step using audio.
3. Explain concepts clearly using examples.
4. Answer follow-up questions patiently.
5. Maintain a supportive and encouraging tone.
6. Once you are initialized, immediately start helping the user with the problem

Start by analyzing the image and providing an initial audio explanation based on the TUTOR_PROMPT and the image content.
"""

# Configuration for the Live API (from example)
# Note: Only AUDIO response is specified here. If you need text too,
# you might need to adjust or handle text separately if the API allows.
LIVE_CONFIG = types.LiveConnectConfig(
    response_modalities=[
        "audio",
        # Add "text" here if the API supports simultaneous audio/text response streams
    ],
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            # Using the voice from the example
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck") 
        )
    ),
    # Add audio input config if required by API
    # audio_input_config=types.AudioInputConfig(sample_rate_hertz=SEND_SAMPLE_RATE)
)

class GeminiTutor:
    def __init__(self, api_key: str, image_path: str = None):
        if not api_key:
            raise ValueError("API key is required. Set GOOGLE_API_KEY environment variable.")
        self.api_key = api_key
        self.image_path = image_path
        self.pya = pyaudio.PyAudio()
        self.audio_stream = None
        self.session = None
        self.audio_in_queue = asyncio.Queue() # Queue for incoming audio from Gemini
        self.out_queue = asyncio.Queue(maxsize=20) # Queue for outgoing audio/image data to Gemini
        self.initial_image_sent = False
        self.change_image_event = asyncio.Event()
        
        # Initialize the Gemini Client (using v1alpha as per example)
        self.client = genai.Client(http_options={"api_version": "v1alpha"}, api_key=self.api_key)

        logger.info("Gemini tutor initialized successfully")

    def _load_image_from_path(self, path):
        """Load an image, prepare for API (base64 encoded)."""
        if not path or not os.path.exists(path):
            logger.error(f"Image path does not exist or not provided: {path}")
            return None
        try:
            logger.info(f"Loading image from: {path}")
            img = PIL.Image.open(path)
            # Optional resizing - remove if not needed
            img.thumbnail([1024, 1024]) 
            
            img_format = img.format if img.format else "PNG"
            if img_format.upper() not in ["JPEG", "PNG", "WEBP"]:
                logger.warning(f"Unsupported image format {img_format}, attempting to save as PNG.")
                mime_type = "image/png"
                img_format = "PNG"
            else:
                mime_type = f"image/{img_format.lower()}"
                 
            image_io = io.BytesIO()
            # Save with appropriate format based on mime_type logic
            save_format = mime_type.split('/')[1].upper() # Extract format (JPEG, PNG, WEBP)
            img.save(image_io, format=save_format) 
            image_io.seek(0)
            image_bytes = image_io.read()
            logger.info(f"Image loaded successfully ({len(image_bytes)} bytes, {mime_type})")
            
            # Return base64 encoded data as used in the example session.send
            return {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode()}
        except Exception as e:
            logger.error(f"Error loading image: {e}", exc_info=True)
            return None

    async def send_text(self):
        """Process text input from the user and send via session.send."""
        while True:
            text = await asyncio.to_thread(
                input,
                "\nEnter a question, 'change' to load a new image, or 'q' to quit > ",
            )
            if not self.session:
                logger.warning("Session not ready for text input, please wait.")
                continue
                
            if text.lower() == "q":
                logger.info("User requested exit via text input.")
                # Signal other tasks to stop gracefully if possible, then break
                # For now, just break the loop, run will handle cancellation
                break 
            elif text.lower() == "change":
                new_path = await asyncio.to_thread(
                    input,
                    "Enter the new image path > ",
                )
                if new_path:
                    self.image_path = new_path.strip().strip('"')
                    self.initial_image_sent = False
                    self.change_image_event.set() # Signal the image processing task
                    logger.info(f"Image path changed to: {self.image_path}")
                continue

            # Send text input using session.send (as per example)
            logger.info(f"Sending text: {text}")
            try:
                 await self.session.send(input=text or ".", end_of_turn=True)
            except Exception as e:
                logger.error(f"Error sending text: {e}", exc_info=True)
        logger.info("Send text task finished.")
        
    async def process_image(self):
        """Monitors image path changes and puts initial prompt/image into out_queue."""
        while True:
            await self.change_image_event.wait() # Wait until signaled to change/load
            self.change_image_event.clear() # Reset the event
            
            if not self.session:
                logger.warning("Session not ready for image processing, waiting...")
                await asyncio.sleep(1) # Wait a bit before retrying
                self.change_image_event.set() # Re-signal to retry processing
                continue

            if not self.initial_image_sent and self.image_path:
                logger.info(f"Processing image: {self.image_path}")
                image_data = await asyncio.to_thread(self._load_image_from_path, self.image_path)
                
                if image_data:
                    try:
                        logger.info("Putting initial prompt and image data into send queue...")
                        # Put prompt and image into the queue for send_realtime task
                        await self.out_queue.put(TUTOR_PROMPT)
                        await self.out_queue.put(image_data)
                        await self.out_queue.put(
                            "Please analyze the image and start guiding me via audio."
                        )
                        # Maybe add end_of_turn=True if required after initial multimodal input?
                        # Check API specifics.
                        
                        self.initial_image_sent = True
                        logger.info("Initial image and prompt queued for sending.")
                    except Exception as e:
                        logger.error(f"Error queueing initial image/prompt: {e}", exc_info=True)
                        self.initial_image_sent = False # Reset flag on failure
                else:
                    logger.error(f"Failed to load image: {self.image_path}. Please check the path.")
                    self.initial_image_sent = False 
                    
            # Brief pause 
            await asyncio.sleep(0.1) 

    async def send_realtime(self):
        """Sends data (audio/image) from the out_queue via session.send."""
        while True:
            if not self.session:
                await asyncio.sleep(0.1)
                continue
            try:
                msg = await self.out_queue.get()
                if msg is None: # Sentinel to stop
                     logger.info("Received stop signal for send_realtime.")
                     break
                logger.debug(f"Sending message type: {type(msg)}")
                await self.session.send(input=msg)
                self.out_queue.task_done()
            except Exception as e:
                 logger.error(f"Error in send_realtime: {e}", exc_info=True)
                 # Decide if we need to break or continue
                 await asyncio.sleep(0.1)
        logger.info("Send realtime task finished.")

    async def listen_audio(self):
        """Capture audio from the microphone and put it into out_queue."""
        audio_stream = None
        try:
            # --- Outer Try: For stream opening ---
            mic_info = self.pya.get_default_input_device_info()
            logger.info(f"Using microphone: {mic_info['name']}")
            audio_stream = await asyncio.to_thread(
                self.pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                input_device_index=mic_info["index"],
                frames_per_buffer=CHUNK_SIZE,
            )
            logger.info("Microphone stream opened. Listening...")

            # --- Loop moved inside the outer try ---
            while True:
                if not self.session:
                     await asyncio.sleep(0.1) # Wait if session not ready
                     continue
                try:
                    # --- Inner Try: For reading/queueing ---
                    data = await asyncio.to_thread(audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)
                    await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
                except OSError as e:
                     # Handle specific, potentially harmless errors
                     logger.warning(f"Error reading from audio stream (likely harmless overflow): {e}")
                     await asyncio.sleep(0.01) 
                except Exception as e:
                     # Catch other critical errors during read/queue
                     logger.error(f"Unexpected error in listen_audio loop: {e}", exc_info=True)
                     break # Exit the while loop on critical errors

        except Exception as e:
             # --- Outer Except: Catches stream opening errors ---
             logger.error(f"Failed to open or initialize microphone stream: {e}", exc_info=True)
             raise asyncio.CancelledError("Microphone initialization failed") # Reraise to signal failure
        finally:
            # --- Finally: Always runs to close the stream ---
            if audio_stream:
                logger.info("Closing microphone stream in listen_audio.")
                try:
                    await asyncio.to_thread(audio_stream.stop_stream)
                    await asyncio.to_thread(audio_stream.close)
                except Exception as e:
                    # Log error during close but don't prevent further cleanup
                    logger.error(f"Error closing audio stream: {e}") 
        logger.info("Listen audio task finished.")
                 
    async def receive_audio(self):
        """Receive responses from the model via session.receive and queue audio."""
        logger.info("Starting to receive responses...")
        while True:
            if not self.session:
                logger.warning("Receive loop: Session not ready, waiting...")
                await asyncio.sleep(1)
                continue
            try:
                # Use the session.receive() pattern from the example
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data: # Check for audio data
                        logger.debug(f"Received audio chunk: {len(data)} bytes")
                        self.audio_in_queue.put_nowait(data)
                    if text := response.text: # Check for text data
                        # Ensure text is printed clearly
                        print(f"\n[AI Tutor]: {text.strip()}") 
                    # Add handling for errors if the response object has an error field
                    if hasattr(response, 'error') and response.error:
                        logger.error(f"Received error from API in response: {response.error}")
                        # Potentially break or handle differently
                         
                # Handle potential end-of-turn signals or completion if needed
                # (Example didn't explicitly show this, may depend on API behavior)

            except asyncio.CancelledError:
                logger.info("Receive audio task cancelled.")
                break
            except Exception as e:
                # Catching potential errors during receive
                # Errors might indicate session closure or other issues
                logger.error(f"Error receiving responses: {e}", exc_info=True)
                # Break the loop if receive fails critically
                break
        logger.info("Receive audio task finished.")
                
    async def play_audio(self):
        """Play audio received from the model via audio_in_queue."""
        stream = None
        try:
            logger.info("Initializing audio playback stream...")
            stream = await asyncio.to_thread(
                self.pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=RECEIVE_SAMPLE_RATE, # Use receive rate from example
                output=True,
            )
            logger.info("Audio playback stream opened.")
            while True:
                bytestream = await self.audio_in_queue.get()
                if bytestream is None: # Sentinel value to stop playback
                    logger.info("Received stop signal for audio playback.")
                    self.audio_in_queue.task_done()
                    break 
                logger.debug(f"Playing audio chunk: {len(bytestream)} bytes")
                await asyncio.to_thread(stream.write, bytestream)
                self.audio_in_queue.task_done() # Notify queue that item is processed
        except asyncio.CancelledError:
             logger.info("Play audio task cancelled.")
        except Exception as e:
            logger.error(f"Error in play_audio: {e}", exc_info=True)
        finally:
            if stream:
                logger.info("Closing audio playback stream.")
                try:
                    # Ensure stream operations are also awaited if they block
                    await asyncio.to_thread(stream.stop_stream)
                    await asyncio.to_thread(stream.close)
                except Exception as e:
                    logger.error(f"Error closing playback stream: {e}")
            logger.info("Play audio task finished.")
                     
    async def run(self):
        """Main execution loop: connects to API and manages tasks."""
        main_task_group = None # To manage cancellation
        try:
            logger.info(f"Connecting to Gemini Live API (model: {MODEL_NAME})...")
            # Use the connection pattern from the working example
            async with self.client.aio.live.connect(model=MODEL_NAME, config=LIVE_CONFIG) as session:
                self.session = session
                logger.info("Live API session connected successfully.")
                self.change_image_event.set() # Signal to load the initial image

                async with asyncio.TaskGroup() as tg:
                    main_task_group = tg # Assign task group for potential later use
                    logger.info("Starting background tasks...")
                    # Task for sending text input from user
                    send_text_task = tg.create_task(self.send_text(), name="SendText") 
                    # Task for sending audio/image data queued in out_queue
                    send_realtime_task = tg.create_task(self.send_realtime(), name="SendRealtime")
                    # Task for listening to microphone
                    listen_audio_task = tg.create_task(self.listen_audio(), name="ListenAudio")
                    # Task for managing image path and queueing initial image
                    process_image_task = tg.create_task(self.process_image(), name="ProcessImage") 
                    # Task for receiving responses from Gemini
                    receive_audio_task = tg.create_task(self.receive_audio(), name="ReceiveAudio")
                    # Task for playing back received audio
                    play_audio_task = tg.create_task(self.play_audio(), name="PlayAudio") 

                    print("\n=== AI Math & English Tutor (Real-time Audio Test) ===")
                    if self.image_path:
                        print(f"Attempting to process image: {self.image_path}")
                    else:
                        print("No initial image provided.")
                    print("Microphone is active. Speak or type your questions after the image is processed.")
                    print("Type 'change' to load a different image.")
                    print("Type 'q' to quit.")
                    print("=========================================================\n")
                    
                    # Wait for the send_text task to finish (e.g., user types 'q')
                    # Or handle completion/errors from other critical tasks if needed
                    await send_text_task # Wait for user to quit via text
                    logger.info("Primary task (send_text) completed, initiating shutdown.")
                    # TaskGroup will handle cancellation of other tasks on exit

        except asyncio.CancelledError:
            logger.info("Main run loop cancelled.")
        except Exception as e:
            # Log the main exception that caused the TaskGroup to exit
            logger.error(f"An unexpected error occurred in run: {e}", exc_info=True)
        finally:
            logger.info("Cleaning up resources...")
            
            # Signal queues to stop processing
            if self.out_queue:
                await self.out_queue.put(None) # Signal send_realtime to stop
            if self.audio_in_queue:
                await self.audio_in_queue.put(None) # Signal playback to stop

            # Allow a very brief moment for tasks to potentially react to signals
            # before streams/clients are potentially closed.
            await asyncio.sleep(0.1)

            # PyAudio cleanup (should happen after tasks using pya are done)
            # The audio stream itself is closed within the listen_audio task's finally block
            if self.pya:
                logger.info("Terminating PyAudio.")
                await asyncio.to_thread(self.pya.terminate)

            # Session cleanup (if the API provides a close method)
            if self.session and hasattr(self.session, 'close'):
                 logger.info("Closing Gemini session.")
                 try:
                     # Check if close is awaitable or not
                     if asyncio.iscoroutinefunction(self.session.close):
                         await self.session.close()
                     else:
                         # Assuming it's a synchronous close if not a coroutine
                         await asyncio.to_thread(self.session.close)
                 except Exception as e:
                     logger.error(f"Error closing session: {e}")

            logger.info("Cleanup attempts complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AI Tutor for Math and English (Real-time Audio Test)')
    parser.add_argument(
        "--image",
        type=str,
        default=DEFAULT_IMAGE_PATH,
        help="Path to the image file containing a math or English problem",
    )
    args = parser.parse_args()
    
    if not args.image:
        args.image = input("Enter the path to an image file > ").strip().strip('"') 
        
    if not args.image:
         print("Error: An image path is required.")
         sys.exit(1)
         
    api_key_to_use = API_KEY 
    if not api_key_to_use:
        print("Error: Google API Key not found. ")
        print("Please set the GOOGLE_API_KEY environment variable in a .env file.")
        sys.exit(1)

    try:
        tutor = GeminiTutor(api_key=api_key_to_use, image_path=args.image)
        asyncio.run(tutor.run())
    except ValueError as e:
         print(f"Error: {e}")
         sys.exit(1)
    except KeyboardInterrupt:
         print("\nExiting due to KeyboardInterrupt...")
    except Exception as e:
         print(f"\nAn unexpected error occurred:")
         traceback.print_exc()
    finally:
         print("Application finished.")