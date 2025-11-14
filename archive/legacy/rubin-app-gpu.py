import textwrap
from uuid import uuid4
import warnings
from pathlib import Path

from langchain_core.runnables import RunnablePassthrough
from langchain_core.callbacks import CallbackManager, BaseCallbackHandler
from langchain_core.prompts import PromptTemplate
from langchain_qdrant import Qdrant
from langchain_huggingface import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from langchain.globals import set_verbose, set_debug
from langchain_community.llms import HuggingFacePipeline

from transformers import pipeline
import panel as pn

set_debug(True)
set_verbose(True)

from download_models import load_transformer_model

warnings.filterwarnings("ignore")


def get_chain(callback_handlers: list[BaseCallbackHandler], input_prompt_template: str):
    retriever = db.as_retriever(
        callbacks=callback_handlers,
        search_type="mmr",
        search_kwargs={"k": 2},
    )

    callback_manager = CallbackManager(callback_handlers)

    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,
        temperature=0.8,
        do_sample=True,
        return_full_text=False,
    )

    olmo = HuggingFacePipeline(pipeline=pipe, callback_manager=callback_manager)

    prompt_template = PromptTemplate.from_template(
        template=tokenizer.chat_template,
        template_format="jinja2",  # set the template format to jinja2
        partial_variables={
            # add generation prompt to the template, this option is from the model metadata
            "add_generation_prompt": True,
            "eos_token": "<|endoftext|>",  # set the end of sentence token
        },
    )

    transformed_prompt_template = PromptTemplate.from_template(
        prompt_template.partial(
            messages=[
                {
                    "role": "user",  # set the role to user, this allows for user input to be passed to the model
                    # the input prompt template, must have `context` and `question` keys to work
                    "content": input_prompt_template,
                }
            ]
        ).format()
    )

    def format_docs(docs):
        return "\n\n".join([d.page_content for d in docs])

    def show_docs(docs):
        for callback_handler in callback_handlers:
            callback_handler.on_retriever_end(docs, run_id=uuid4())
        return docs

    def expand_query_with_synonyms(query):
        if "Rubin" in query:
            query += " LSST Large Synoptic Survey Telescope"
        return query

    return (
        {
            "context": expand_query_with_synonyms | retriever | show_docs | format_docs,
            "question": RunnablePassthrough(),
        }
        | transformed_prompt_template
        | olmo
    )


async def callback(contents, user, instance):
    callback_handler = pn.chat.langchain.PanelCallbackHandler(
        instance, user="OLMo", avatar="🌳"
    )
    chain = get_chain(
        callback_handlers=[callback_handler],
        input_prompt_template=input_prompt_template,
    )
    await chain.ainvoke(contents)


pn.extension()

model, tokenizer = load_transformer_model()

base_path = Path(__file__).parent.parent.resolve()
qdrant_path = (
    base_path / "data" / "vector_stores" / "rubin_qdrant"
)  # TODO Change for needed vector store
qdrant_collection = "rubin_telescope"  # TODO Change for needed vector store

embedding = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L12-v2")

client = QdrantClient(path=str(qdrant_path))
db = Qdrant(
    client=client,
    collection_name=qdrant_collection,
    embeddings=embedding,  # Use embedding.encode if embedding is directly from SentenceTransformer
)

input_prompt_template = textwrap.dedent(
    (
        "You are an astrophysics expert with a focus on the Rubin telescope project "
        "(formerly known as Large Synoptic Survey Telescope - LSST). Please answer "
        "the question on astrophysics based on the following context:\n\n"
        "{context}\n\n"
        "Question: {question}\n"
    )
)

chat_interface = pn.chat.ChatInterface(callback=callback)

if __name__ == "__main__":
    pn.serve({"/": chat_interface}, port=5006, websocket_origin="*", show=False)
