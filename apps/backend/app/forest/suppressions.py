"""Persistent user decisions about automatically inferred links."""
import json

from sqlalchemy.dialects.sqlite import insert

from app.db.models import NotebookRelationSuppression, utc_now
from app.document_processing.checkpoints import fingerprint


def pair_key(source_book, source_block, target_book, target_block, relation_type):
    endpoints = sorted([(source_book, source_block or ''), (target_book, target_block or '')])
    return fingerprint([endpoints, relation_type])


def suppress(db, relation):
    key = pair_key(relation.source_notebook_id, relation.source_block_id,
                   relation.target_notebook_id, relation.target_block_id, relation.relation_type)
    db.execute(insert(NotebookRelationSuppression).values(pair_key=key,
        left_notebook_id=relation.source_notebook_id, right_notebook_id=relation.target_notebook_id,
        anchors_json=json.dumps([relation.source_block_id, relation.target_block_id, relation.relation_type]),
        created_at=utc_now()).on_conflict_do_nothing(index_elements=['pair_key']))


def is_suppressed(db, source, target, relation_type):
    key = pair_key(source['notebook_id'], source['block_id'], target['notebook_id'],
                   target['block_id'], relation_type)
    return db.get(NotebookRelationSuppression, key) is not None
