import sys
import os
sys.path.append(os.path.abspath('backend'))
import asyncio
from services.gemini_service import GeminiReportingService
from schemas import DocumentMetadata

async def test():
    gemini = GeminiReportingService()
    doc_meta = DocumentMetadata(attached=False, file_type='none')
    intent = await gemini.normalize_intent("Write a report on space exploration.", doc_meta)
    print("Intent:", intent)
    report = await gemini.generate_report(intent=intent)
    print("Report:", report)

if __name__ == "__main__":
    asyncio.run(test())
