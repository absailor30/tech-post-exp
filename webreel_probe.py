"""Scratch: capture a real GitHub page into a reel on the runner and commit it to the branch for review."""
import subprocess, sys
import webreel
specs=[{"kind":"hook","headline":"Run AI models like DeepSeek and Qwen locally","kicker":"Repo 1 of 100"},
 {"kind":"content","headline":"What it does","body":"Get up and running with Kimi, GLM, MiniMax, DeepSeek, gpt-oss, Qwen, Gemma and other models.","idx":2,"total":6},
 {"kind":"content","headline":"What is inside","body":"Install options for Mac, Windows and Linux, a quickstart, and community integrations.","idx":3,"total":6},
 {"kind":"content","headline":"The facts","body":"Over 182,000 GitHub stars, MIT licence, written in Go. Created June 2023.","idx":4,"total":6},
 {"kind":"content","headline":"Before you use it","body":"Check the README and licence first.","idx":5,"total":6},
 {"kind":"cta","headline":"Follow for all 100","body":"One AI repo explained in plain words, every day."}]
import os; os.makedirs("preview", exist_ok=True)
webreel.build_web_reel(specs, "https://github.com/ollama/ollama", "preview/ollama_webreel.mp4")
