import uuid

from django.db import models


def dataset_upload_path(instance: "Dataset", filename: str) -> str:
    return f"datasets/{instance.id}/{filename}"


class Dataset(models.Model):
    """Represents a saved dataset artifact in any stage of the pipeline."""

    STAGE_SIMULATED = "simulated"
    STAGE_RAW = "raw"
    STAGE_CLEANED = "cleaned"
    STAGE_SYNTHETIC = "synthetic"

    STAGE_CHOICES = [
        (STAGE_SIMULATED, "Simulated"),
        (STAGE_RAW, "Raw"),
        (STAGE_CLEANED, "Cleaned"),
        (STAGE_SYNTHETIC, "Synthetic"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    stage = models.CharField(max_length=32, choices=STAGE_CHOICES, default=STAGE_SIMULATED)
    file = models.FileField(upload_to=dataset_upload_path)
    created_at = models.DateTimeField(auto_now_add=True)
    rows = models.PositiveIntegerField(default=0)
    cols = models.PositiveIntegerField(default=0)
    differentially_private = models.BooleanField(default=False)
    source_dataset = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="synthetic_outputs",
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.name} ({self.stage})"


class PrivacyPolicy(models.Model):
    """Student-level privacy configuration for a dataset."""

    ACCOUNTANT_RDP = "rdp"
    ACCOUNTANT_PRV = "prv"
    ACCOUNTANT_PAC_SYNTH = "pac_synth"
    ACCOUNTANT_CHOICES = [
        (ACCOUNTANT_RDP, "RDP"),
        (ACCOUNTANT_PRV, "PRV"),
        (ACCOUNTANT_PAC_SYNTH, "PAC-Synth DP marginals"),
    ]

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="privacy_policies")
    privacy_unit = models.CharField(max_length=32, default="student")
    student_id_col = models.CharField(max_length=128, default="student_id")
    max_rows_per_student = models.PositiveIntegerField(default=1)
    quasi_identifiers = models.JSONField(default=list, blank=True)
    sensitive_attributes = models.JSONField(default=list, blank=True)
    public_bounds = models.JSONField(default=dict, blank=True)
    epsilon = models.FloatField(default=3.0)
    delta = models.FloatField(default=1e-5)
    accountant = models.CharField(max_length=16, choices=ACCOUNTANT_CHOICES, default=ACCOUNTANT_PAC_SYNTH)
    reporting_length = models.PositiveSmallIntegerField(default=2)
    noise_multiplier = models.FloatField(default=1.5)
    max_grad_norm = models.FloatField(default=1.0)
    epochs = models.PositiveIntegerField(default=20)
    batch_size = models.PositiveIntegerField(default=128)
    sampling_rate = models.FloatField(default=0.1)
    seed = models.PositiveIntegerField(default=42)
    status = models.CharField(max_length=32, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Privacy policy for {self.dataset_id}"


class BudgetLedger(models.Model):
    """Records DP budget consumption for a dataset."""

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="budget_ledger")
    action = models.CharField(max_length=128)
    epsilon_spent = models.FloatField(default=0.0)
    delta = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @staticmethod
    def enforce_cap(current_spent: float, cap: float, requested: float) -> None:
        if current_spent + requested > cap:
            raise ValueError(f"DP budget cap would be exceeded: {current_spent + requested} > {cap}.")

    def __str__(self) -> str:
        return f"{self.action}: eps={self.epsilon_spent}, delta={self.delta}"
