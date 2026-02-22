import socket
import os
import subprocess
import time

# CONFIG - CHANGE THIS TO YOUR VPS IP!
SERVER_IP = "34.93.92.230"
PORT = 9000

def record_and_send():
    print("🎤 Recording... (Speak now)")
    
    # Record 5 seconds of audio using Termux API
    # outputting raw PCM 16-bit 16000Hz mono
    filename = "input.pcm"
    
    # Using ffmpeg to record from mic (pulse) to raw file
    # This requires 'pulseaudio' to be running in Termux
    # 'pacmd list-sources' to find mic if needed, but default usually works
    
    # Start Pulseaudio if not running
    os.system("pulseaudio --start --exit-idle-time=-1 > /dev/null 2>&1")
    
    cmd = f"ffmpeg -y -f pulse -i default -t 5 -ar 16000 -ac 1 -f s16le {filename} -loglevel quiet"
    os.system(cmd)
    
    print("📤 Sending to Rook...")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((SERVER_IP, PORT))
            
            with open(filename, 'rb') as f:
                s.sendall(f.read())
            
            # Shut down write side to signal we are done sending
            s.shutdown(socket.SHUT_WR)
            
            # Listen for reply
            reply = s.recv(1024).decode('utf-8')
            print(f"♟️ Rook says: {reply}")
            
            # Speak it!
            os.system(f"termux-tts-speak \"{reply}\"")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    while True:
        record_and_send()
        time.sleep(1) # Breath between turns