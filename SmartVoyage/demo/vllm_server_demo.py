# pip install  vllm
import subprocess
import sys

def main():
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", "export/qwen2.5-merged/",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--dtype", "float16",
        "--gpu-memory-utilization", "0.9", #如果OOM 应该把这个调小点比如0.85
        "--max-model-len", "8192",
    ]

    print("Starting vLLM server...")
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
    # print(sys.executable)