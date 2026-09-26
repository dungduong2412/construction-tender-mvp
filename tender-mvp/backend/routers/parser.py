"""Parser adapter router — expose adapter contract endpoints."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/contract")
async def adapter_contract():
    """Returns the documented adapter contract."""
    return {
        "description": "Azure Document Intelligence Adapter Contract",
        "version": "1.0",
        "submit_endpoint": {
            "method": "POST",
            "url": "{AZURE_DOC_INTEL_ENDPOINT}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version=2024-11-30",
            "headers": {"Ocp-Apim-Subscription-Key": "<key>", "Content-Type": "application/pdf"},
            "body": "<raw PDF bytes>",
            "response": "202 Accepted, header: Operation-Location: <poll_url>",
        },
        "poll_endpoint": {
            "method": "GET",
            "url": "<Operation-Location from submit>",
            "headers": {"Ocp-Apim-Subscription-Key": "<key>"},
            "response": {
                "status": "succeeded | running | failed",
                "analyzeResult": {
                    "pages": [{"pageNumber": 1, "tables": []}],
                    "tables": [
                        {
                            "rowCount": "<int>",
                            "columnCount": "<int>",
                            "cells": [
                                {
                                    "rowIndex": "<int>",
                                    "columnIndex": "<int>",
                                    "kind": "columnHeader|content",
                                    "content": "<string>",
                                    "boundingRegions": [{"pageNumber": "<int>", "polygon": []}],
                                }
                            ],
                        }
                    ],
                },
            },
        },
        "mock_mode": "Set MOCK_PARSER=true to use fixtures/bang_tien_luong_mock.json",
    }
