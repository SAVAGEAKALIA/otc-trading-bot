"""Disk-spooled global ownership for every identity in disjoint source shards."""
from __future__ import annotations
from pathlib import Path
import sqlite3
import tempfile

# Audit-only live prefix measurement: ~1.27GB for the registered seven days.
# 8GiB allows >6x measured metadata headroom while keeping exhaustion explicit.
DATABASE_BYTE_CAP=8*1024*1024*1024
TEMPORARY_BYTE_CAP=2*DATABASE_BYTE_CAP+16*1024*1024
SQLITE_CACHE_BYTE_CAP=2*1024*1024
KEY_BATCH_ROW_CAP=256
KEY_BATCH_BYTE_CAP=256*1024


def key_bytes(row):
    """Exact UTF-8 key payload and fixed-width SQLite integer accounting."""
    return sum(len(value.encode('utf-8')) if isinstance(value,str) else 8 for value in row)


class IdentityLedger:
    """A UNIQUE constraint outlives replay tails without keeping source IDs in RAM.

    One transaction admits one already-censused shard. Source cursors supply at
    most one key batch; only IDs and sequences reach the ledger, never payloads.
    The SQLite database, cache and total temporary files have explicit caps.
    Default SQLite journaling and synchronization are retained.
    """
    def __init__(self):
        self.temporary=None;self.connection=None;self.path=None
        self.audit={'storage':'temporary_sqlite','policy':'owned_disjoint_shards_no_identity_reuse',
            'checked_session_ids':0,'checked_frame_ids':0,'checked_session_sequences':0,
            'checked_event_ids':0,'segments_checked':0,'violations':0,
            'database_byte_cap':DATABASE_BYTE_CAP,'temporary_byte_cap':TEMPORARY_BYTE_CAP,
            'sqlite_cache_byte_cap':SQLITE_CACHE_BYTE_CAP,'key_batch_row_cap':KEY_BATCH_ROW_CAP,
            'key_batch_byte_cap':KEY_BATCH_BYTE_CAP,'maximum_key_batch_rows':0,
            'maximum_key_batch_bytes':0,'maximum_database_bytes':0,'maximum_temporary_bytes':0,
            'cleanup_completed':False}
        try:
            self.temporary=tempfile.TemporaryDirectory(prefix='otc-source-identity-')
            self.path=Path(self.temporary.name)/'identities.sqlite'
            self.connection=sqlite3.connect(self.path)
            self.connection.execute('PRAGMA page_size=4096')
            self.connection.execute('PRAGMA max_page_count='+str(DATABASE_BYTE_CAP//4096))
            self.connection.execute('PRAGMA cache_size=-'+str(SQLITE_CACHE_BYTE_CAP//1024))
            self.connection.execute('PRAGMA mmap_size=0')
            self.connection.execute('PRAGMA temp_store=FILE')
            self.connection.executescript('''
CREATE TABLE session_ids(identity TEXT PRIMARY KEY NOT NULL) WITHOUT ROWID;
CREATE TABLE frame_ids(identity TEXT PRIMARY KEY NOT NULL,session_id TEXT NOT NULL,sequence INTEGER NOT NULL,UNIQUE(session_id,sequence)) WITHOUT ROWID;
CREATE TABLE event_ids(identity TEXT PRIMARY KEY NOT NULL) WITHOUT ROWID;
''')
            self._sizes()
        except BaseException:
            self.close();raise

    def _sizes(self):
        database=self.path.stat().st_size
        total=sum(item.stat().st_size for item in self.path.parent.iterdir() if item.is_file())
        self.audit['maximum_database_bytes']=max(self.audit['maximum_database_bytes'],database)
        self.audit['maximum_temporary_bytes']=max(self.audit['maximum_temporary_bytes'],total)
        if database>DATABASE_BYTE_CAP or total>TEMPORARY_BYTE_CAP:
            raise ValueError('Global source identity ledger exceeds deterministic disk byte cap')

    def admit(self,source):
        if self.connection is None:raise ValueError('Global source identity ledger is closed')
        inventories=(
            ('session_ids','SELECT session_id FROM sessions WHERE transition=\'open\'','INSERT INTO session_ids VALUES (?)','checked_session_ids'),
            ('frame_ids','SELECT frame_id,session_id,sequence FROM receipts','INSERT INTO frame_ids VALUES (?,?,?)','checked_frame_ids'),
            ('event_ids','SELECT event_id FROM observations','INSERT INTO event_ids VALUES (?)','checked_event_ids'))
        counts={}
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            for table,select,insert,field in inventories:
                count=0;cursor=source.execute(select)
                try:
                    for batch,byte_count in self._batches(cursor):
                        self.audit['maximum_key_batch_rows']=max(self.audit['maximum_key_batch_rows'],len(batch))
                        self.audit['maximum_key_batch_bytes']=max(self.audit['maximum_key_batch_bytes'],byte_count)
                        self.connection.executemany(insert,batch);count+=len(batch)
                        self._sizes()
                        # Release the caller's reference before the generator
                        # accumulates the next batch, retaining one batch only.
                        del batch
                finally:cursor.close()
                counts[field]=count
            self.connection.commit();self._sizes()
        except BaseException as error:
            self.connection.rollback();self.audit['violations']+=1
            if isinstance(error,sqlite3.IntegrityError):
                raise ValueError('Global source identity reused across owned disjoint shards: '+table) from error
            if isinstance(error,sqlite3.DatabaseError):
                raise ValueError('Global source identity ledger could not admit bounded metadata') from error
            raise
        for field,count in counts.items():self.audit[field]+=count
        self.audit['checked_session_sequences']+=counts['checked_frame_ids']
        self.audit['segments_checked']+=1

    @staticmethod
    def _batches(cursor):
        # One pending source key at most. fetchmany(row_cap) could allocate
        # 32MiB for legal 64KiB frame/session keys before a byte guard runs.
        batch=[];byte_count=0
        while True:
            row=cursor.fetchone()
            if row is None:break
            size=key_bytes(row)
            if size>KEY_BATCH_BYTE_CAP:
                raise ValueError('Global source identity key exceeds deterministic batch byte cap')
            if batch and (len(batch)>=KEY_BATCH_ROW_CAP or byte_count+size>KEY_BATCH_BYTE_CAP):
                yield batch,byte_count
                batch=[];byte_count=0
            batch.append(row);byte_count+=size
        if batch:yield batch,byte_count

    def close(self):
        try:
            if self.connection is not None:self.connection.close()
        finally:
            self.connection=None
            if self.temporary is not None:self.temporary.cleanup()
            self.temporary=None;self.path=None;self.audit['cleanup_completed']=True
