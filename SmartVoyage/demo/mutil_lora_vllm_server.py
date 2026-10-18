import subprocess
import sys
import os

def main():
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",

        # base model
        "--model", "Qwen/Qwen2.5-1.5B-Instruct/",

        # server
        "--host", "0.0.0.0",
        "--port", "8000",

        # precision & memory
        "--dtype", "float16",
        "--gpu-memory-utilization", "0.8",
        "--max-model-len", "8192",

        # ===== LoRA 关键参数 =====
        "--enable-lora",
        "--lora-modules",
        "tcm=/workspace/LLaMA-Factory/saves/Qwen2.5-1.5B-Instruct/lora/train_2026-06-05-13-11-43",   # 中医
        "law=/workspace/LLaMA-Factory/saves/Qwen2.5-1.5B-Instruct/lora/train_2026-03-08-13-47-54",   # 法律
        "cs=/workspace/LLaMA-Factory/saves/Qwen2.5-1.5B-Instruct/lora/train_2026-03-08-13-47-54",     # 客服
        "--max-loras", "3",
        "--max-lora-rank", "8",
    ]

    print("Starting vLLM server with multiple LoRA adapters...")
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    main()

'''
{"object":"list","data":[{"id":"Qwen/Qwen2.5-1.5B-Instruct/","object":"model","created":1787105736,"owned_by":"vllm","root":"Qwen/Qwen2.5-1.5B-Instruct/","parent":null,"max_model_len":8192,"permission":[{"id":"modelperm-6dff4fa58f414be8908931842dde0655","object":"model_permission","created":1787105736,"allow_create_engine":false,"allow_sampling":true,"allow_logprobs":true,"allow_search_indices":false,"allow_view":true,"allow_fine_tuning":false,"organization":"*","group":null,"is_blocking":false}]},{"id":"tcm","object":"model","created":1787105736,"owned_by":"vllm","root":"/workspace/LLaMA-Factory/saves/Qwen2.5-1.5B-Instruct/lora/train_2026-06-05-13-11-43","parent":"Qwen/Qwen2.5-1.5B-Instruct/","max_model_len":null,"permission":[{"id":"modelperm-2ccb19c0c1774a75a4c91b9cb0863fbe","object":"model_permission","created":1787105736,"allow_create_engine":false,"allow_sampling":true,"allow_logprobs":true,"allow_search_indices":false,"allow_view":true,"allow_fine_tuning":false,"organization":"*","group":null,"is_blocking":false}]},{"id":"law","object":"model","created":1787105736,"owned_by":"vllm","root":"/workspace/LLaMA-Factory/saves/Qwen2.5-1.5B-Instruct/lora/train_2026-03-08-13-47-54","parent":"Qwen/Qwen2.5-1.5B-Instruct/","max_model_len":null,"permission":[{"id":"modelperm-04b2e4a76a1b4f4dabec9a89f83853c5","object":"model_permission","created":1787105736,"allow_create_engine":false,"allow_sampling":true,"allow_logprobs":true,"allow_search_indices":false,"allow_view":true,"allow_fine_tuning":false,"organization":"*","group":null,"is_blocking":false}]},{"id":"cs","object":"model","created":1787105736,"owned_by":"vllm","root":"/workspace/LLaMA-Factory/saves/Qwen2.5-1.5B-Instruct/lora/train_2026-03-08-13-47-54","parent":"Qwen/Qwen2.5-1.5B-Instruct/","max_model_len":null,"permission":[{"id":"modelperm-06fc4de4f9544f5caa14e10788846ab7","object":"model_permission","created":1787105736,"allow_create_engine":false,"allow_sampling":true,"allow_logprobs":true,"allow_search_indices":false,"allow_view":true,"allow_fine_tuning":false,"organization":"*","group":null,"is_blocking":false}]}]}
'''