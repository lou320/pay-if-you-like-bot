import socket
import speech_recognition as sr
from pydub import AudioSegment
import io
import subprocess
import threading

# CONFIG
HOST = '0.0.0.0'
PORT = 9000

def process_audio(audio_data, conn):
    try:
        # Convert Raw PCM (from phone) to WAV container in memory
        # Assuming 16kHz, Mono, 16-bit PCM
        audio = AudioSegment(
            data=audio_data,
            sample_width=2,
            frame_rate=16000,
            channels=1
        )
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)

        # STT (Speech to Text) - Using Google Free Tier (SpeechRecognition lib)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_content = recognizer.record(source)
        
        try:
            print("Listening...")
            text = recognizer.recognize_google(audio_content)
            print(f"User said: {text}")
            
            # AI Logic (Using the local Gemini CLI I have access to)
            # We keep it short for speed
            cmd = f'gemini "You are Rook. User said: \'{text}\'. Reply in 1 short sentence."'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            reply = result.stdout.strip()
            
            if not reply:
                reply = "I heard you, but I have nothing to say."
                
            print(f"Rook: {reply}")
            
            # Send TEXT back to phone (Phone will speak it)
            conn.sendall(reply.encode('utf-8'))
            
        except sr.UnknownValueError:
            print("Could not understand audio")
            conn.sendall(b"I didn't catch that.")
        except sr.RequestError:
            print("STT API Error")
            conn.sendall(b"My hearing is offline.")

    except Exception as e:
        print(f"Error processing: {e}")

def start_server():
    print(f"Rook Ear is listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        
        while True:
            conn, addr = s.accept()
            print(f"Connected by {addr}")
            data_buffer = b""
            
            # Simple Protocol: Receive until connection closes or specific marker
            # For this prototype, we'll listen for 5 seconds of audio chunks then process
            # Ideally we'd use silence detection on the stream, but let's keep it robust first
            
            try:
                # Receive loop
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    data_buffer += data
                    
                    # If we have ~5 seconds of audio (16k * 2 bytes * 5s = 160000 bytes)
                    # We process it to keep it conversational. 
                    # Real VAD is harder to implement without dependencies.
                    if len(data_buffer) > 160000: 
                        break 
                        
                if data_buffer:
                    process_audio(data_buffer, conn)
                    
            except Exception as e:
                print(f"Connection error: {e}")
            finally:
                conn.close()

if __name__ == "__main__":
    start_server()