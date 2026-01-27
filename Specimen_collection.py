import json
import boto3
import time
import logging

# ================= AWS CLIENT =================
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# ================= LOGGER =================
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ================= SYSTEM PROMPTS =================
SYSTEM_PROMPT = """
You are a Clinical Laboratory Assistant providing detailed test procedures.

MANDATORY FORMAT:

1. TEST NAME

2. SPECIMEN REQUIREMENTS
3. COLLECTION PROCEDURE
4. HANDLING & STORAGE
5. PROCESSING STEPS
6. PRECAUTIONS

Rules:
- Exact measurements only
- NO diagnosis
- NO treatment
"""

IMAGE_PROMPT = """
You are a Clinical Laboratory Report Analyzer.

Provide:
1. REPORT SUMMARY
2. INTERPRETATION
3. DIETARY RECOMMENDATIONS
4. LIFESTYLE RECOMMENDATIONS
5. FOLLOW-UP ADVICE

IMPORTANT:
- Educational only
- Advise consulting a healthcare professional
"""

# ================= MAIN HANDLER =================
def lambda_handler(event, context):
    start = time.time()
    logger.info(f"Event: {json.dumps(event)}")

    # ---- CORS ----
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return cors(200, "")

    body = parse_body(event)
    mode = body.get("mode", "").lower()

    if not mode:
        return cors(400, {"error": "mode is required"})

    if mode in ["clinical", "voice", "text"]:
        text = body.get("prompt") or body.get("transcript") or ""
        return handle_text(text, start)

    elif mode == "image":
        image_b64 = body.get("image_base64") or body.get("image")
        return handle_image(image_b64, start)

    else:
        return cors(400, {"error": f"Invalid mode: {mode}"})


# ================= TEXT HANDLER =================
def handle_text(text, start):
    if not text.strip():
        return cors(400, {"error": "Empty input"})

    prompt = f"{SYSTEM_PROMPT}\n\nLaboratory Test Requested:\n{text}"

    try:
        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}]
                    }
                ],
                "inferenceConfig": {
                    "max_new_tokens": 1500,
                    "temperature": 0.2,
                    "top_p": 0.9
                }
            })
        )

        result = json.loads(response["body"].read())
        answer = result["output"]["message"]["content"][0]["text"]
        tokens = result.get("usage", {}).get("outputTokens", 0)

        return success(answer, start, tokens)

    except Exception as e:
        logger.error(str(e))
        return cors(500, {"error": str(e)})


# ================= IMAGE HANDLER =================
def handle_image(image_b64, start):
    if not image_b64:
        return cors(400, {"error": "Image missing"})

    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    try:
        response = bedrock.invoke_model(
            modelId="amazon.nova-2-lite-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": "png",
                                    "source": {"bytes": image_b64}
                                }
                            },
                            {"text": IMAGE_PROMPT}
                        ]
                    }
                ],
                "inferenceConfig": {
                    "max_new_tokens": 2000,
                    "temperature": 0.3
                }
            })
        )

        result = json.loads(response["body"].read())
        answer = result["output"]["message"]["content"][0]["text"]
        tokens = result.get("usage", {}).get("outputTokens", 0)

        return success(answer, start, tokens)

    except Exception as e:
        logger.error(str(e))
        return cors(500, {"error": str(e)})


# ================= HELPERS =================
def parse_body(event):
    try:
        return json.loads(event.get("body", "{}"))
    except Exception:
        return {}

def success(answer, start, tokens):
    return cors(200, {
        "answer": answer.strip(),
        "latency_seconds": round(time.time() - start, 2),
        "token_count": tokens
    })

def cors(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS"
        },
        "body": json.dumps(body) if body else ""
    }
