import os

# テストでは常に決定的なScriptedLLMを使う（Gemini API不要）
os.environ["CLOUDMEDIC_SCRIPTED"] = "1"
