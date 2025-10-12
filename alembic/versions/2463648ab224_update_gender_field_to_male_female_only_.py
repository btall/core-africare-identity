"""update gender field to male/female only (legal requirement)

Revision ID: 2463648ab224
Revises: 
Create Date: 2025-10-13 00:40:43.841917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2463648ab224'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Mise à jour du champ gender pour ne garder que male/female.

    Contexte: Réglementation sénégalaise et africaine - seuls les genres
    homme et femme sont légalement reconnus.

    Migration:
    1. Met à jour les valeurs 'other' et 'unknown' existantes vers 'male' par défaut
    2. Modifie la longueur de la colonne de VARCHAR(20) à VARCHAR(10)

    Note: Les valeurs existantes 'other' et 'unknown' seront converties en 'male'
    par défaut. Il est recommandé de réviser manuellement ces enregistrements si nécessaire.
    """
    # Étape 1: Migrer les valeurs 'other' et 'unknown' vers 'male'
    op.execute(
        """
        UPDATE patients
        SET gender = 'male'
        WHERE gender IN ('other', 'unknown')
        """
    )

    # Étape 2: Réduire la taille de la colonne (PostgreSQL supporte VARCHAR sans perte)
    op.alter_column(
        'patients',
        'gender',
        type_=sa.String(length=10),
        existing_type=sa.String(length=20),
        existing_nullable=False
    )


def downgrade() -> None:
    """Rollback: restaure la colonne gender à l'état précédent.

    Attention: Cette opération ne peut pas restaurer les valeurs 'other' et 'unknown'
    qui ont été converties en 'male' lors de l'upgrade.
    """
    # Restaurer la taille de colonne
    op.alter_column(
        'patients',
        'gender',
        type_=sa.String(length=20),
        existing_type=sa.String(length=10),
        existing_nullable=False
    )
