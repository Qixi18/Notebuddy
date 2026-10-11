"""Compatibility exports for the original API schema module."""

from app.schemas.assistant import (
    AssistantClaim,
    AssistantRequest,
    AssistantResponse,
    AssistantSource,
)
from app.schemas.backup import (
    BackupExportRequest,
    BackupPreviewRead,
    BackupRecordRead,
    RestoreRequest,
)
from app.schemas.conversations import (
    ConversationCreate,
    ConversationMessageCreate,
    ConversationMessageRead,
    ConversationRead,
    MessageEvidenceRead,
)
from app.schemas.courses import CourseCreate, CourseRead, CourseUpdate, DeletionPreview
from app.schemas.coverage import CoverageLocation, CoverageRead
from app.schemas.feedback import FeedbackCreate, FeedbackRead, FeedbackUpdate
from app.schemas.jobs import JobRead
from app.schemas.knowledge import (
    KnowledgeChangeRead,
    KnowledgeEdgeRead,
    KnowledgeGraphRead,
    KnowledgeNodeRead,
    KnowledgeNodeSourceRead,
    KnowledgeNodeWithSourcesRead,
)
from app.schemas.materials import (
    BlockRead,
    MaterialRead,
    PageEvidenceRead,
    PageRead,
    SourceRefRead,
    UploadMaterialResponse,
    WebSourceRead,
)
from app.schemas.notes import NoteRead, NoteRevisionRead, NoteUpdate
from app.schemas.proposals import KnowledgeProposalRead, NoteSuggestionRead, ProposalReview
from app.schemas.provider import ProviderCallRead
from app.schemas.settings import (
    ProviderConnectivityTestRequest,
    SettingsStatus,
    SettingsUpdate,
    SettingsUpdateResponse,
)
from app.schemas.terms import TermExplanationRequest, TermExplanationResponse, TermExplanationSource

__all__ = [
    'AssistantClaim',
    'AssistantRequest',
    'AssistantResponse',
    'AssistantSource',
    'BackupExportRequest',
    'BackupPreviewRead',
    'BackupRecordRead',
    'BlockRead',
    'ConversationCreate',
    'ConversationMessageCreate',
    'ConversationMessageRead',
    'ConversationRead',
    'CourseCreate',
    'CourseRead',
    'CourseUpdate',
    'CoverageLocation',
    'CoverageRead',
    'DeletionPreview',
    'FeedbackCreate',
    'FeedbackRead',
    'FeedbackUpdate',
    'JobRead',
    'KnowledgeChangeRead',
    'KnowledgeEdgeRead',
    'KnowledgeGraphRead',
    'KnowledgeNodeRead',
    'KnowledgeNodeSourceRead',
    'KnowledgeNodeWithSourcesRead',
    'KnowledgeProposalRead',
    'MaterialRead',
    'MessageEvidenceRead',
    'NoteRead',
    'NoteRevisionRead',
    'NoteSuggestionRead',
    'NoteUpdate',
    'PageEvidenceRead',
    'PageRead',
    'ProposalReview',
    'ProviderCallRead',
    'ProviderConnectivityTestRequest',
    'RestoreRequest',
    'SettingsStatus',
    'SettingsUpdate',
    'SettingsUpdateResponse',
    'SourceRefRead',
    'TermExplanationRequest',
    'TermExplanationResponse',
    'TermExplanationSource',
    'UploadMaterialResponse',
    'WebSourceRead',
]
