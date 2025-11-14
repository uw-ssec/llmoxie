import textwrap
from uuid import uuid4
import warnings
from pathlib import Path

from langchain_core.runnables import RunnablePassthrough
from langchain_core.callbacks import CallbackManager, BaseCallbackHandler
from langchain_core.prompts import PromptTemplate
from langchain_community.llms import LlamaCpp
from langchain_qdrant import Qdrant
from langchain_huggingface import HuggingFaceEmbeddings
from qdrant_client import QdrantClient

from ssec_tutorials import download_olmo_model

warnings.filterwarnings("ignore")

import panel as pn


def get_chain(callback_handlers: list[BaseCallbackHandler], input_prompt_template: str):
    # 1. Set up the vector database retriever.
    # This line of code will create a retriever object that
    # will be used to retrieve documents from the vector database.
    retriever = db.as_retriever(
        callbacks=callback_handlers,  # pass the result of the retrieval to the callback handler
        search_type="mmr",  # the mmr (maximal marginal relevance, a typical information retrieval tactic) search
        search_kwargs={"k": 2},  # return top 2 results
    )

    # 2. Setup the Langchain callback manager to handle callbacks from Langchain LLM object.
    # At which results are passed to the callback handler.
    callback_manager = CallbackManager(callback_handlers)

    # 3. Setup the Langchain llama.cpp model object.
    # In our case, we are using the `OLMo-7B-Instruct` model.
    # llama-cpp-python is a Python binding for llama.cpp C++ library as mentioned in previous modules.
    olmo = LlamaCpp(
        model_path=str(model_path),  # the path to the OLMo model in GGUF file format
        callback_manager=callback_manager,  # set the callback manager to handle callbacks
        temperature=0.8,  # set the randomness of the model's output
        n_ctx=4096,  # set limit for the length of the input context
        max_tokens=512,  # set limit for the length of the generated text
        verbose=False,  # determines whether the model should print out debug information
        echo=False,  # determines whether the input prompt should be included in the output
    )

    # 4. Set up the initial Langchain Prompt Template using text based jinja2 format
    prompt_template = PromptTemplate.from_template(
        template=olmo.client.metadata[
            "tokenizer.chat_template"
        ],  # get the chat template from the model metadata
        template_format="jinja2",  # set the template format to jinja2
        partial_variables={
            "add_generation_prompt": True,  # add generation prompt to the template, this option is from the model metadata
            "eos_token": "<|endoftext|>",  # set the end of sentence token
        },
    )

    # 5. Transform the Prompt Template to include the user role and the context
    # This will allow the model to generate text based on the context provided.
    # However, after setting this new template, the model will be limited to
    # generating text based on the created prompt template with input of
    # `context` and `question` keys.
    transformed_prompt_template = PromptTemplate.from_template(
        prompt_template.partial(
            # The default chat template takes a list of messages with a role and content
            # to setup this particular app, we will only pass a single message with the user role
            # and the input prompt content
            messages=[
                {
                    "role": "user",  # set the role to user, this allows for user input to be passed to the model
                    "content": input_prompt_template,  # the input prompt template, must have `context` and `question` keys to work
                }
            ]
        ).format()
    )

    # 6. Define the `format_docs` function to format the retrieved Langchain documents object to simple string
    def format_docs(docs):
        text = "\n\n".join([d.page_content for d in docs])
        return text

    # 7. Define the `show_docs` function to display the retrieved documents to app panel
    # this is currently a small hack to display the retrieved documents to the app panel
    # as mentioned in https://github.com/langchain-ai/langchain/issues/7290
    def show_docs(docs):
        for callback_handler in callback_handlers:
            callback_handler.on_retriever_end(
                docs,  # pass the retrieved documents to the callback handler
                run_id=uuid4(),  # generate a random run id
            )
        return docs

    # 8. Return the Langchain chain object
    # The way the chain reads is as follows:
    return (
        {
            # The Vector Database retriever documents,
            # which is then passed to the `show_docs` function,
            # which is then passed to the `format_docs` function for formatting
            "context": retriever | show_docs | format_docs,
            # The Question asked by the user from the Chat Text Input Interface is passed in as well
            "question": RunnablePassthrough(),
        }
        # The dictionary above that contains text values for `context` and `question` is now passed
        # to the transformed prompt template so that the final prompt text can be generated
        | transformed_prompt_template
        # The full final prompt text with both context and question is passed to the OLMo model
        # for generation of the final output. Note that this final prompt text cannot exceed the maximum
        # `n_ctx` input context value set in the OLMo model above.
        | olmo
    )


async def callback(contents, user, instance):
    # 1. Create a panel callback handler
    # The Langchain PanelCallbackHandler is useful for rendering and streaming the chain of thought
    # from Langchain objects like Tools, Agents, and Chains.
    # It inherits from Langchain’s BaseCallbackHandler.
    # Here we set the user to be the model name "OLMo" with an avatar of a tree emoji "🌳"
    # for the tree of knowledge.
    callback_handler = pn.chat.langchain.PanelCallbackHandler(
        instance, user="OLMo", avatar="🌳"
    )

    # 2. Set to not return the full generated result at the end of the generation;
    # this prevents the model from repeating the result in the interface
    callback_handler.on_llm_end = lambda response, *args, **kwargs: None

    # 3. Create and setup the Langchain chain object with the callback handler and input prompt template
    chain = get_chain(
        callback_handlers=[callback_handler],
        input_prompt_template=input_prompt_template,
    )

    # 4. Run the chain with the input contents
    _ = await chain.ainvoke(contents)


pn.extension()

model_path = download_olmo_model()

# Created via: https://github.com/uw-ssec/tutorials/blob/main/Archive/SciPy2024/appendix/qdrant-vector-database-creation.ipynb
qdrant_path = Path.home() / ".cache/ssec_tutorials/scipy_qdrant"
qdrant_collection = "arxiv_astro-ph_abstracts_astropy_github_documentation"

embedding = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L12-v2")

# db = Qdrant.from_existing_collection(
#     collection_name=qdrant_collection, embedding=embedding, path=qdrant_path
# )

client = QdrantClient(path=str(qdrant_path))
db = Qdrant(client=client, collection_name=qdrant_collection, embeddings=embedding)

input_prompt_template = textwrap.dedent(
    """\
You are an astrophysics expert. Please answer the question on astrophysics based on the following context:

{context}

Question: {question}
"""
)

chat_interface = pn.chat.ChatInterface(callback=callback)

# Enable serving the app on a web URL
if __name__ == "__main__":
    pn.serve({"/": chat_interface}, port=5006, websocket_origin="*", show=False)
