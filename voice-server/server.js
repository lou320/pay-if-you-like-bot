const express = require('express');
const https = require('https');
const fs = require('fs');
const socketIo = require('socket.io');
const path = require('path');

const app = express();

// SSL Configuration (Using the certs we generated for the VPN)
// This enables HTTPS, which allows the browser to grant Microphone access
const options = {
  key: fs.readFileSync('/root/cert/rook.scammerdb.website/privkey.pem'),
  cert: fs.readFileSync('/root/cert/rook.scammerdb.website/fullchain.pem')
};

const server = https.createServer(options, app);
const io = socketIo(server);

app.use(express.static(path.join(__dirname, 'public')));

io.on('connection', (socket) => {
    console.log('User connected via Secure Voice Link');

    socket.on('voice_input', (text) => {
        console.log('User said:', text);
        
        // Simulating AI response for now (since we lack a local LLM CLI)
        // In a full build, this would hit an API
        const response = `I heard you say: "${text}". My voice logic is running!`;
        
        socket.emit('ai_reply', response);
    });
});

// Port 8443 is supported by Cloudflare HTTPS Proxy
const PORT = 8443;
server.listen(PORT, '0.0.0.0', () => {
    console.log(`Secure Voice Server running on https://scammerdb.website:${PORT}`);
});