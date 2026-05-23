"""Base processor interface for multi-modal input normalization."""

from abc import ABC, abstractmethod

from src.models.schemas import InputFragment, ProcessingResult


class BaseProcessor(ABC):
    @abstractmethod
    def process(self, fragment: InputFragment) -> ProcessingResult:
        """Normalize a fragment into structured text for the BRD agent."""
