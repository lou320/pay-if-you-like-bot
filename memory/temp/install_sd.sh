#!/bin/bash

# Rook's "Freedom Factory" Installer for Google Cloud (NVIDIA T4)
# Installs Stable Diffusion WebUI (Automatic1111)

echo "♟️ Rook is setting up your Freedom Factory..."

# 1. Update System & Install Basics
sudo apt update
sudo apt install -y wget git python3 python3-venv libgl1 libglib2.0-0 google-perftools

# 2. Clone the Repository
if [ ! -d "stable-diffusion-webui" ]; then
    git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git
fi
cd stable-diffusion-webui

# 3. Create a launch script that listens on 0.0.0.0 (Public Access)
# We add --share to generate a temporary public link (Gradio) just in case Firewall fails
# We add --xformers for speed on T4 GPUs
cat > run_factory.sh <<EOF
#!/bin/bash
./webui.sh --listen --enable-insecure-extension-access --xformers --gradio-auth rook:freedom
EOF

chmod +x run_factory.sh

echo "----------------------------------------------------------------"
echo "✅ Installation Complete."
echo "To start your factory, run:"
echo "   cd stable-diffusion-webui && ./run_factory.sh"
echo ""
echo "NOTE: You will need to open TCP Port 7860 in Google Cloud Firewall!"
echo "----------------------------------------------------------------"