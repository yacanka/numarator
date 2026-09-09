import re
import secrets
import string
from abc import ABC, abstractmethod
from typing import Any, Dict, Type

from django.utils import timezone

from .checksum import calculate_checksum

class SegmentConfig:
    def __init__(self, **kwargs):
        """Store raw segment options."""
        self.options = kwargs

    def get(self, key, default=None):
        """Return an option by key with a default fallback."""
        return self.options.get(key, default)

class BaseSegment(ABC):
    segment_type = ''
    label = ''
    description = ''
    icon = ''

    def __init__(self, config: SegmentConfig):
        """Create a configured segment and validate its options."""
        self.config = config
        self.validate_config()

    @abstractmethod
    def generate(self, context: Dict[str, Any]) -> str:
        """Generate this segment value for a generation context."""

    @abstractmethod
    def preview(self) -> str:
        """Return a representative non-persistent segment preview."""

    @abstractmethod
    def validate_config(self) -> None:
        """Validate segment configuration and raise ValueError on failure."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize segment metadata for API responses."""
        return {'type': self.segment_type, 'config': self.config.options, 'preview': self.preview()}

class StaticSegment(BaseSegment):
    segment_type, label, description, icon = 'static', 'Static Text', 'Fixed text', 'text'

    def validate_config(self) -> None:
        value = self.config.get('value', '')
        if not value or len(value) > 50:
            raise ValueError('Static value is required and cannot exceed 50 characters')

    def generate(self, context: Dict[str, Any]) -> str:
        """Return the configured fixed text."""
        return self.config.get('value', '')

    def preview(self) -> str:
        """Return the configured fixed text preview."""
        return self.config.get('value', 'TEXT')

class DateSegment(BaseSegment):
    segment_type, label, description, icon = 'date', 'Date', 'Date based value', 'calendar'
    formats = {'YYYY': '%Y', 'YY': '%y', 'MM': '%m', 'DD': '%d', 'YYYYMMDD': '%Y%m%d', 'YYYYMM': '%Y%m', 'Q': 'Q', 'WW': '%W'}

    def validate_config(self) -> None:
        if self.config.get('format', 'YYYY') not in self.formats:
            raise ValueError(f"Invalid date format. Allowed: {', '.join(self.formats)}")

    def generate(self, context: Dict[str, Any]) -> str:
        """Render the configured date format."""
        now = context.get('timestamp', timezone.now())
        current_time = timezone.localtime(now) if timezone.is_aware(now) else now
        fmt = self.config.get('format', 'YYYY')
        return str(((current_time.month - 1) // 3) + 1) if fmt == 'Q' else current_time.strftime(self.formats[fmt])

    def preview(self) -> str:
        """Render a preview using the current timestamp."""
        return self.generate({'timestamp': timezone.now()})

class SequenceSegment(BaseSegment):
    segment_type, label, description, icon = 'sequence', 'Sequence', 'Incrementing number', 'number'

    def validate_config(self) -> None:
        self._validate_int('padding', 4, 1, 20)
        self._validate_int('start', 1, 0, None)
        self._validate_int('step', 1, 1, None)

    def generate(self, context: Dict[str, Any]) -> str:
        """Return the padded current sequence value."""
        return str(context.get('sequence_value', 1)).zfill(self.config.get('padding', 4))

    def preview(self) -> str:
        """Return a padded sequence preview."""
        return str(self.config.get('start', 1)).zfill(self.config.get('padding', 4))

    def _validate_int(self, key: str, default: int, minimum: int, maximum) -> None:
        value = self.config.get(key, default)
        if not isinstance(value, int) or value < minimum or (maximum and value > maximum):
            raise ValueError(f'{key} must be an integer in the allowed range')

class YearlyResetSequenceSegment(SequenceSegment):
    segment_type, label, description, icon = 'yearly_sequence', 'Yearly Sequence', 'Yearly reset sequence', 'refresh'

class RandomSegment(BaseSegment):
    segment_type, label, description, icon = 'random', 'Random', 'Random characters', 'shuffle'
    char_sets = {'numeric': string.digits, 'alpha': string.ascii_uppercase, 'alphanumeric': string.ascii_uppercase + string.digits, 'hex': '0123456789ABCDEF'}

    def validate_config(self) -> None:
        length = self.config.get('length', 6)
        if not isinstance(length, int) or length < 1 or length > 20:
            raise ValueError('Length must be integer between 1 and 20')
        if self.config.get('char_type', 'alphanumeric') not in self.char_sets:
            raise ValueError(f"Invalid char_type. Allowed: {', '.join(self.char_sets)}")

    def generate(self, context: Dict[str, Any]) -> str:
        """Return a secure random string."""
        chars = self.char_sets[self.config.get('char_type', 'alphanumeric')]
        return ''.join(secrets.choice(chars) for _ in range(self.config.get('length', 6)))

    def preview(self) -> str:
        """Return a random-looking preview string."""
        return self.generate({})

class ChecksumSegment(BaseSegment):
    segment_type, label, description, icon = 'checksum', 'Checksum', 'Validation digit', 'check'
    algorithms = {'luhn', 'mod10', 'mod11', 'simple'}

    def validate_config(self) -> None:
        if self.config.get('algorithm', 'mod10') not in self.algorithms:
            raise ValueError(f"Invalid algorithm. Allowed: {', '.join(sorted(self.algorithms))}")

    def generate(self, context: Dict[str, Any]) -> str:
        """Calculate the checksum for the current partial number."""
        digits = re.sub(r'\D', '', context.get('partial_number', ''))
        return calculate_checksum(digits, self.config.get('algorithm', 'mod10'))

    def preview(self) -> str:
        """Return a symbolic checksum preview."""
        return 'C'

class ContextSegment(BaseSegment):
    segment_type, label, description, icon = 'context', 'Context', 'Dynamic context value', 'tag'

    def validate_config(self) -> None:
        if not self.config.get('key'):
            raise ValueError("Context segment requires 'key'")

    def generate(self, context: Dict[str, Any]) -> str:
        """Return the configured context value normalized to uppercase."""
        value = context.get('context_data', {}).get(self.config.get('key'), self.config.get('default', 'UNKNOWN'))
        return str(value).upper()[:self.config.get('max_length', 10)]

    def preview(self) -> str:
        """Return the context placeholder preview."""
        return f"[{self.config.get('key', 'CONTEXT').upper()}]"

class SeparatorSegment(BaseSegment):
    segment_type, label, description, icon = 'separator', 'Separator', 'Delimiter', 'minus'
    allowed = {'-', '/', '.', '_', '|', ':', '\\'}

    def validate_config(self) -> None:
        if self.config.get('value', '-') not in self.allowed:
            raise ValueError(f"Invalid separator. Allowed: {', '.join(sorted(self.allowed))}")

    def generate(self, context: Dict[str, Any]) -> str:
        """Return the configured separator."""
        return self.config.get('value', '-')

    def preview(self) -> str:
        """Return the configured separator preview."""
        return self.config.get('value', '-')


SEGMENT_REGISTRY: Dict[str, Type[BaseSegment]] = {
    cls.segment_type: cls
    for cls in [StaticSegment, DateSegment, SequenceSegment, YearlyResetSequenceSegment, RandomSegment, ChecksumSegment, ContextSegment, SeparatorSegment]
}


def get_segment_class(segment_type: str) -> Type[BaseSegment]:
    """Return a segment class by type or raise a validation error."""
    if segment_type not in SEGMENT_REGISTRY:
        raise ValueError(f'Unknown segment type: {segment_type}')
    return SEGMENT_REGISTRY[segment_type]


def get_available_segments():
    """Return metadata for all registered segment types."""
    return [{'type': cls.segment_type, 'label': cls.label, 'description': cls.description, 'icon': cls.icon} for cls in SEGMENT_REGISTRY.values()]
