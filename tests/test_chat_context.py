import unittest

import app


class DummyUploadFile:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


class ChatContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_context_from_uploaded_files_and_existing_text(self):
        files = [DummyUploadFile("notes.txt", b"The mitochondria is the powerhouse")]

        context = await app.build_chat_context(
            context="The student is revising cell biology.",
            uploaded_files=files,
        )

        self.assertIn("The mitochondria is the powerhouse", context)
        self.assertIn("The student is revising cell biology.", context)


if __name__ == "__main__":
    unittest.main()
