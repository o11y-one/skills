from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([("system", "Answer in one word."), ("human", "{question}")])
chain = prompt | FakeListChatModel(responses=["TEST-answer"])

if __name__ == "__main__":
    print(chain.invoke({"question": "Is the eval running?"}).content)
