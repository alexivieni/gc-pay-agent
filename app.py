"""Chat with the agent in a browser.

    streamlit run app.py

Same agent, same sign-in as ask.py: it uses your `az login` session, so there are no keys.
The page runs on your machine; nothing new is deployed to Azure.
"""

import streamlit as st

from common import ask, cited_files, clients

EXAMPLES = [
    "How much vacation leave do I earn after 8 years under PA?",
    "And after 15 years?",
    "How much overtime do I get?",
    "How many days a week do I have to be in the office?",
]

st.set_page_config(page_title="GC Pay Agent")
st.title("GC Pay Agent")
st.caption(
    "Answers questions from the PA, EC and IT collective agreements and cites the article. "
    "Information only, not official pay or HR advice."
)


@st.cache_resource
def get_client():
    _, openai = clients()
    return openai


try:
    openai = get_client()
except SystemExit as missing:  # common.setting() exits when .env is incomplete
    st.error(str(missing))
    st.stop()


def new_conversation() -> None:
    st.session_state.conversation_id = openai.conversations.create().id
    st.session_state.messages = []


def show(text: str) -> None:
    # Escape dollar signs, which Streamlit would otherwise render as maths
    st.markdown(text.replace("$", "\\$"))


def show_sources(sources: list[str]) -> None:
    st.caption("Sources: " + (", ".join(sources) if sources else "none cited"))


if "conversation_id" not in st.session_state:
    new_conversation()

with st.sidebar:
    st.subheader("Try asking")
    for example in EXAMPLES:
        if st.button(example):
            st.session_state.pending = example
    st.divider()
    if st.button("New conversation"):
        new_conversation()
        st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        show(message["content"])
        if message["role"] == "assistant":
            show_sources(message["sources"])

question = st.chat_input("Ask about pay, leave or overtime") or st.session_state.pop("pending", None)

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        show(question)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the agreements..."):
                response = ask(openai, question, st.session_state.conversation_id)
                answer = response.output_text or ""
                sources = cited_files(openai, response)
        except Exception as err:  # show the problem in the page instead of a stack trace
            st.error(f"{type(err).__name__}: {err}")
            st.session_state.messages.pop()
            st.stop()
        show(answer)
        show_sources(sources)
    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
