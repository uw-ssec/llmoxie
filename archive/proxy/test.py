from openai import OpenAI

# endpoint = "https://carlo-mgr0qeth-eastus2.cognitiveservices.azure.com/openai/v1/"
endpoint = "http://localhost:8888/v1/"
api_key = "not used"

model_name = "gpt-5-mini"


client = OpenAI(
    base_url=f"{endpoint}",
    api_key=api_key
)

completion = client.chat.completions.create(
    model=model_name,
    store=True,
    messages=[
        {
            "role": "user",
            "content": "What is the capital of France?",
        }
    ],
)

print(completion.choices[0].message)