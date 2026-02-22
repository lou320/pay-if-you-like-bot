import socket
import os
import time

# CONFIG - CHANGE THIS TO YOUR VPS IP!
SERVER_IP = "34.93.92.230"
PORT = 9000

def record_and_send():
    print("🎤 Recording... (Speak now)")
    
    # Clean up old files
    if os.path.exists("input.pcm"):
        os.remove("input.pcm")
    if os.path.exists("input.wav"):
        os.remove("input.wav")
        
    # FIX: Removed '-q' because on some Termux versions it means "Quit Now" instead of "Quiet"
    # We just record for 5 seconds
    os.system("termux-microphone-record -l 5 -f input.wav")
    
    # Check if WAV was created
    if not os.path.exists("input.wav"):
        print("❌ Recording failed. Check microphone permissions.")
        # Try to clean up any stuck recording
        os.system("termux-microphone-record -q")
        time.sleep(2)
        return

    # Convert WAV to Raw PCM
    os.system("ffmpeg -y -i input.wav -f s16le -ac 1 -ar 16000 input.pcm -loglevel quiet")
    
    if not os.path.exists("input.pcm"):
        print("❌ Conversion failed.")
        return

    print("📤 Sending to Rook...")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((SERVER_IP, PORT))
            
            with open("input.pcm", 'rb') as f:
                s.sendall(f.read())
            
            s.shutdown(socket.SHUT_WR)
            
            reply = s.recv(1024).decode('utf-8')
            print(f"♟️ Rook says: {reply}")
            
            # Speak the reply
            os.system(f"termux-tts-speak \"{reply}\"")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    # Ensure any previous recording is stopped
    os.system("termux-microphone-record -q > /dev/null 2>&1")
    time.sleep(1)
    
    while True:
        record_and_send()
        # Small delay to let the TTS finish speaking before recording again
        time.sleep(3)