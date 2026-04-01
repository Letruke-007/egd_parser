from datetime import datetime

from pydantic import BaseModel, Field


class IdentityDocumentResponse(BaseModel):
    document_type: str | None = None
    series: str | None = None
    number: str | None = None
    issued_by: str | None = None
    issue_date: str | None = None
    raw: str | None = None


class DepartureValidationResponse(BaseModel):
    scheme: str | None = None
    applicable: bool | None = None
    passed: bool | None = None


class DepartureResponse(BaseModel):
    status: str | None = None
    reason: str | None = None
    raw: str | None = None
    death_date: str | None = None
    departure_date: str | None = None
    act_record_number: str | None = None
    act_record_date: str | None = None
    issued_by: str | None = None
    destination_address: str | None = None
    validation: DepartureValidationResponse = Field(default_factory=DepartureValidationResponse)


class PropertyAddressResponse(BaseModel):
    street: str | None = None
    house: str | None = None
    building: str | None = None
    structure: str | None = None
    apartment: str | None = None
    full: str | None = None


class ManagementCompanyResponse(BaseModel):
    name: str | None = None


class OwnerResponse(BaseModel):
    full_name: str | None = None
    ownership_share: str | None = None


class RegisteredPersonResponse(BaseModel):
    full_name: str | None = None
    birthday_date: str | None = None
    passport: IdentityDocumentResponse = Field(default_factory=IdentityDocumentResponse)
    departure: DepartureResponse = Field(default_factory=DepartureResponse)


class RegisteredPersonsBlockResponse(BaseModel):
    count: int = 0
    persons: list[RegisteredPersonResponse] = Field(default_factory=list)


class Page1Response(BaseModel):
    document_date: str | None = None
    administrative_okrug: str | None = None
    district: str | None = None
    passport: IdentityDocumentResponse = Field(default_factory=IdentityDocumentResponse)
    property_address: PropertyAddressResponse = Field(default_factory=PropertyAddressResponse)
    management_company: ManagementCompanyResponse = Field(default_factory=ManagementCompanyResponse)
    settlement_type: str | None = None
    owners: list[OwnerResponse] = Field(default_factory=list)
    primary_tenant: str | None = None
    ownership_documents: list[str] = Field(default_factory=list)


class Page2Response(BaseModel):
    registered_persons_constantly: RegisteredPersonsBlockResponse = Field(default_factory=RegisteredPersonsBlockResponse)
    registered_persons_temporary: RegisteredPersonsBlockResponse = Field(default_factory=RegisteredPersonsBlockResponse)
    benefits: str | None = None


class ExtractedDataResponse(BaseModel):
    document_type: str = "egd"
    page_1: Page1Response = Field(default_factory=Page1Response)
    page_2: Page2Response = Field(default_factory=Page2Response)


class MetadataResponse(BaseModel):
    ocr_engine: str | None = None
    page_images: list[str] = Field(default_factory=list)
    ocr_preview: dict[str, str] = Field(default_factory=dict)
    extraction_trace: dict = Field(default_factory=dict)


class ParseResponse(BaseModel):
    filename: str
    status: str = "accepted"
    pages: int = 0
    warnings: list[str] = Field(default_factory=list)
    extracted_data: ExtractedDataResponse = Field(default_factory=ExtractedDataResponse)
    metadata: MetadataResponse = Field(default_factory=MetadataResponse)


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    total_files: int
    completed_files: int = 0
    failed_files: int = 0


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_files: int
    completed_files: int = 0
    failed_files: int = 0
    error: str | None = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse] = Field(default_factory=list)


class JobFileResult(BaseModel):
    filename: str
    status: str
    pages: int = 0
    warnings: list[str] = Field(default_factory=list)
    extracted_data: ExtractedDataResponse = Field(default_factory=ExtractedDataResponse)
    metadata: MetadataResponse = Field(default_factory=MetadataResponse)
    error: str | None = None


class JobResultsResponse(JobStatusResponse):
    files: list[JobFileResult] = Field(default_factory=list)


class CleanupResponse(BaseModel):
    deleted_jobs: int


class UploadedJobFileResponse(BaseModel):
    file_index: int
    filename: str
    stored_filename: str
    size_bytes: int


class UploadedJobFileListResponse(BaseModel):
    job_id: str
    files: list[UploadedJobFileResponse] = Field(default_factory=list)
