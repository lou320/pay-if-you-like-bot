import socket
import os
import time

# CONFIG - CHANGE THIS TO YOUR VPS IP!
SERVER_IP = "34.93.92.230"
PORT = 9000

def record_and_send():
    print("🎤 Recording... (Speak now)")
    
    # METHOD 2: Use Termux Native API (More reliable than PulseAudio)
    # Record 5 seconds to a WAV file
    if os.path.exists("input.pcm"):
        os.remove("input.pcm")
        
    # Record
    os.system("termux-microphone-record -l 5 -f input.wav -q")
    
    # Convert WAV to Raw PCM for the server
    # -f s16le = Signed 16-bit Little Endian
    # -ac 1 = Mono
    # -ar 16000 = 16kHz
    os.system("ffmpeg -y -i input.wav -f s16le -ac 1 -ar 16000 input.pcm -loglevel quiet")
    
    if not os.path.exists("input.pcm"):
        print("❌ Error: Recording failed. Is Termux:API installed?")
        time.sleep(2)
        return

    print("📤 Sending to Rook...")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10) # 10s timeout
            s.connect((SERVER_IP, PORT))
            
            with open("input.pcm", 'rb') as f:
                s.sendall(f.read())
            
            s.shutdown(socket.SHUT_WR)
            
            reply = s.recv(1024).decode('utf-8')
            print(f"♟️ Rook says: {reply}")
            
            os.system(f"termux-tts-speak \"{reply}\"")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    # Clean up old files
    os.system("termux-microphone-record -q") # Stop any hanging recordings
    
    while True:
        record_and_send()
        time.sleep(1)