import google.generativeai as genai
import json
with open('vpn_bot/config.json') as f:
    conf = json.load(f)
genai.configure(api_key=conf['gemini_api_key'])
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)