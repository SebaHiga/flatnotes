import glob
import os
import re
import shutil
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Literal, Set, Tuple

import whoosh
from whoosh import writing
from whoosh.analysis import CharsetFilter, StemmingAnalyzer
from whoosh.fields import DATETIME, ID, KEYWORD, TEXT, SchemaClass
from whoosh.highlight import ContextFragmenter, WholeFragmenter
from whoosh.index import Index, LockError
from whoosh.qparser import MultifieldParser
from whoosh.qparser.dateparse import DateParserPlugin
from whoosh.query import Every
from whoosh.searching import Hit
from whoosh.support.charset import accent_map

from helpers import get_env, is_valid_filename
from logger import logger

from .. import fuzzy
from ..base import BaseNotes
from ..models import Note, NoteCreate, NoteUpdate, SearchResult

MARKDOWN_EXT = ".md"
INDEX_SCHEMA_VERSION = "6"
# Cap on how much of a note's content is scored during fuzzy search, to
# bound the cost of the subsequence DP for very large notes.
MAX_FUZZY_CONTENT_CHARS = 20000

StemmingFoldingAnalyzer = StemmingAnalyzer() | CharsetFilter(accent_map)


class IndexSchema(SchemaClass):
    filename = ID(unique=True, stored=True)
    last_modified = DATETIME(stored=True, sortable=True)
    # Best-known creation date. There's no true creation timestamp available
    # (the filesystem doesn't expose reliable birth times on Linux, and
    # notes aren't otherwise tracked before they're first indexed), so this
    # is backfilled from last_modified the first time a note is indexed and
    # then preserved across every later re-index of that same filename (see
    # _sync_index/_add_note_to_index).
    created = DATETIME(stored=True, sortable=True)
    title = TEXT(
        field_boost=2.0, analyzer=StemmingFoldingAnalyzer, sortable=True
    )
    content = TEXT(analyzer=StemmingFoldingAnalyzer)
    tags = KEYWORD(lowercase=True, field_boost=2.0)


class FileSystemNotes(BaseNotes):
    TAGS_RE = re.compile(r"(?:(?<=^#)|(?<=\s#))[a-zA-Z0-9_-]+(?=\s|$)")
    CODEBLOCK_RE = re.compile(r"`{1,3}.*?`{1,3}", re.DOTALL)
    TAGS_WITH_HASH_RE = re.compile(
        r"(?:(?<=^)|(?<=\s))#[a-zA-Z0-9_-]+(?=\s|$)"
    )
    ATTACHMENT_REF_RE = re.compile(r"attachments/([^\s)\"']+)")

    def __init__(self):
        self.storage_path = get_env("FLATNOTES_PATH", mandatory=True)
        if not os.path.exists(self.storage_path):
            raise NotADirectoryError(
                f"'{self.storage_path}' is not a valid directory."
            )
        self.index = self._load_index()
        self._sync_index_with_retry(optimize=True)

    def create(self, data: NoteCreate) -> Note:
        """Create a new note."""
        filepath = self._path_from_title(data.title)
        self._write_file(filepath, data.content)
        return Note(
            title=data.title,
            content=data.content,
            last_modified=os.path.getmtime(filepath),
        )

    def get(self, title: str) -> Note:
        """Get a specific note."""
        is_valid_filename(title)
        filepath = self._path_from_title(title)
        content = self._read_file(filepath)
        return Note(
            title=title,
            content=content,
            last_modified=os.path.getmtime(filepath),
        )

    def update(self, title: str, data: NoteUpdate) -> Note:
        """Update a specific note."""
        is_valid_filename(title)
        filepath = self._path_from_title(title)
        if data.new_title is not None:
            new_filepath = self._path_from_title(data.new_title)
            if filepath != new_filepath and os.path.isfile(new_filepath):
                raise FileExistsError(
                    f"Failed to rename. '{data.new_title}' already exists."
                )
            os.rename(filepath, new_filepath)
            title = data.new_title
            filepath = new_filepath
        if data.new_content is not None:
            self._write_file(filepath, data.new_content, overwrite=True)
            content = data.new_content
        else:
            content = self._read_file(filepath)
        return Note(
            title=title,
            content=content,
            last_modified=os.path.getmtime(filepath),
        )

    def delete(self, title: str) -> None:
        """Delete a specific note."""
        is_valid_filename(title)
        filepath = self._path_from_title(title)
        os.remove(filepath)

    def search(
        self,
        term: str,
        sort: Literal["score", "title", "last_modified", "created"] = "score",
        order: Literal["asc", "desc"] = "desc",
        limit: int = None,
        fuzzy: bool = False,
        include_content: bool = False,
    ) -> Tuple[SearchResult, ...]:
        """Search the index for the given term."""
        self._sync_index_with_retry()
        if fuzzy:
            return self._fuzzy_search(
                term,
                include_content=include_content,
                sort=sort,
                order=order,
                limit=limit,
            )
        term = self._pre_process_search_term(term)
        with self.index.searcher() as searcher:
            # Parse Query
            if term == "*":
                query = Every()
            else:
                parser = MultifieldParser(
                    self._fieldnames_for_term(term), self.index.schema
                )
                parser.add_plugin(DateParserPlugin())
                query = parser.parse(term)

            # Determine Sort By
            # Note: For the 'sort' option, "score" is converted to None as
            # that is the default for searches anyway and it's quicker for
            # Whoosh if you specify None.
            sort = sort if sort in ["title", "last_modified", "created"] else None

            # Determine Sort Direction
            # Note: Confusingly, when sorting by 'score', reverse = True means
            # asc so we have to flip the logic for that case!
            reverse = order == "desc"
            if sort is None:
                reverse = not reverse

            # Run Search
            results = searcher.search(
                query,
                sortedby=sort,
                reverse=reverse,
                limit=limit,
                terms=True,
            )
            return tuple(self._search_result_from_hit(hit) for hit in results)

    def _fuzzy_search(
        self,
        term: str,
        include_content: bool,
        sort: Literal["score", "title", "last_modified", "created"],
        order: Literal["asc", "desc"],
        limit: int,
    ) -> Tuple[SearchResult, ...]:
        """Search using fzf-style fuzzy subsequence matching (see
        ../fuzzy.py) instead of Whoosh's query parser. A note matches if its
        title, or (when include_content is set) its content, matches `term`
        as a fuzzy subsequence."""
        results: List[SearchResult] = []
        with self.index.searcher() as searcher:
            for stored in searcher.all_stored_fields():
                title = self._strip_ext(stored["filename"])

                title_match = fuzzy.fuzzy_score(term, title)

                content_ex_tags = None
                content_match = None
                if include_content:
                    content = self._read_file(self._path_from_title(title))
                    content_ex_tags, _ = self._extract_tags(content)
                    content_ex_tags = content_ex_tags[:MAX_FUZZY_CONTENT_CHARS]
                    content_match = fuzzy.fuzzy_score(term, content_ex_tags)

                if title_match is None and content_match is None:
                    continue

                score = 0.0
                title_highlights = None
                content_highlights = None
                if title_match is not None:
                    title_score, title_indices = title_match
                    # Mirrors IndexSchema's title field_boost=2.0.
                    score += title_score * 2
                    title_highlights = fuzzy.highlight(title, title_indices)
                if content_match is not None:
                    content_score, content_indices = content_match
                    score += content_score
                    content_highlights = fuzzy.content_snippet(
                        content_ex_tags, content_indices
                    )

                results.append(
                    SearchResult(
                        title=title,
                        last_modified=stored["last_modified"].timestamp(),
                        created=stored["created"].timestamp(),
                        score=score,
                        title_highlights=title_highlights,
                        content_highlights=content_highlights,
                        tag_matches=None,
                    )
                )

        reverse = order == "desc"
        if sort == "title":
            results.sort(key=lambda result: result.title, reverse=reverse)
        elif sort == "last_modified":
            results.sort(
                key=lambda result: result.last_modified, reverse=reverse
            )
        elif sort == "created":
            results.sort(key=lambda result: result.created, reverse=reverse)
        else:
            results.sort(key=lambda result: result.score, reverse=reverse)

        if limit is not None:
            results = results[:limit]
        return tuple(results)

    def get_tags(self) -> list[str]:
        """Return a list of all indexed tags. Note: Tags no longer in use will
        only be cleared when the index is next optimized."""
        self._sync_index_with_retry()
        with self.index.reader() as reader:
            tags = reader.field_terms("tags")
            return [tag for tag in tags]

    def get_attachment_references(self) -> Dict[str, List[str]]:
        """Return a mapping of attachment filename to the titles of the
        notes that reference it, derived from attachments/ links in each
        note's content."""
        references: Dict[str, List[str]] = {}
        for filename in self._list_all_note_filenames():
            title = self._strip_ext(filename)
            content = self._read_file(self._path_from_title(title))
            for match in self.ATTACHMENT_REF_RE.finditer(content):
                attachment_filename = urllib.parse.unquote(match.group(1))
                references.setdefault(attachment_filename, []).append(title)
        return references

    @property
    def _index_path(self):
        return os.path.join(self.storage_path, ".flatnotes")

    def _path_from_title(self, title: str) -> str:
        return os.path.join(self.storage_path, title + MARKDOWN_EXT)

    def _get_by_filename(self, filename: str) -> Note:
        """Get a note by its filename."""
        return self.get(self._strip_ext(filename))

    def _load_index(self) -> Index:
        """Load the note index or create new if not exists."""
        index_dir_exists = os.path.exists(self._index_path)
        if index_dir_exists and whoosh.index.exists_in(
            self._index_path, indexname=INDEX_SCHEMA_VERSION
        ):
            logger.info("Loading existing index")
            return whoosh.index.open_dir(
                self._index_path, indexname=INDEX_SCHEMA_VERSION
            )
        else:
            if index_dir_exists:
                logger.info("Deleting outdated index")
                self._clear_dir(self._index_path)
            else:
                os.mkdir(self._index_path)
            logger.info("Creating new index")
            return whoosh.index.create_in(
                self._index_path, IndexSchema, indexname=INDEX_SCHEMA_VERSION
            )

    @classmethod
    def _extract_tags(cls, content) -> Tuple[str, Set[str]]:
        """Strip tags from the given content and return a tuple consisting of:

        - The content without the tags.
        - A set of tags converted to lowercase."""
        content_ex_codeblock = re.sub(cls.CODEBLOCK_RE, "", content)
        _, tags = cls._re_extract(cls.TAGS_RE, content_ex_codeblock)
        content_ex_tags, _ = cls._re_extract(cls.TAGS_RE, content)
        try:
            tags = [tag.lower() for tag in tags]
            return (content_ex_tags, set(tags))
        except IndexError:
            return (content, set())

    def _add_note_to_index(
        self, writer: writing.IndexWriter, note: Note, created: float = None
    ) -> None:
        """Add a Note object to the index using the given writer. If the
        filename already exists in the index an update will be performed
        instead. `created` is the timestamp to record as the note's created
        date; omit it to backfill from the note's last_modified (used when a
        filename is being indexed for the first time and no better date is
        known)."""
        content_ex_tags, tag_set = self._extract_tags(note.content)
        tag_string = " ".join(tag_set)
        writer.update_document(
            filename=note.title + MARKDOWN_EXT,
            last_modified=datetime.fromtimestamp(note.last_modified),
            created=datetime.fromtimestamp(
                created if created is not None else note.last_modified
            ),
            title=note.title,
            content=content_ex_tags,
            tags=tag_string,
        )

    def _list_all_note_filenames(self) -> List[str]:
        """Return a list of all note filenames."""
        return [
            os.path.split(filepath)[1]
            for filepath in glob.glob(
                os.path.join(self.storage_path, "*" + MARKDOWN_EXT)
            )
        ]

    def _sync_index(self, optimize: bool = False, clean: bool = False) -> None:
        """Synchronize the index with the notes directory.
        Specify clean=True to completely rebuild the index"""
        indexed = set()
        # A rename shows up here as one filename disappearing and another
        # appearing, with no way to tell they're the same note other than
        # renaming (a plain os.rename) leaving last_modified untouched. So
        # deleted entries are kept around keyed by their last_modified and,
        # when a "new" file turns out to share that exact mtime, its created
        # date is carried over instead of being backfilled as if it were a
        # brand new note. Content changed in the same request as the rename
        # will change the mtime and defeat this match, in which case created
        # falls back to being backfilled like any other new filename.
        removed_created_by_mtime: Dict[datetime, datetime] = {}
        writer = self.index.writer()
        if clean:
            writer.mergetype = writing.CLEAR  # Clear the index
        with self.index.searcher() as searcher:
            for idx_note in searcher.all_stored_fields():
                idx_filename = idx_note["filename"]
                idx_filepath = os.path.join(self.storage_path, idx_filename)
                # Delete missing
                if not os.path.exists(idx_filepath):
                    writer.delete_by_term("filename", idx_filename)
                    removed_created_by_mtime[idx_note["last_modified"]] = (
                        idx_note["created"]
                    )
                    logger.info(f"'{idx_filename}' removed from index")
                # Update modified
                elif (
                    datetime.fromtimestamp(os.path.getmtime(idx_filepath))
                    != idx_note["last_modified"]
                ):
                    logger.info(f"'{idx_filename}' updated")
                    self._add_note_to_index(
                        writer,
                        self._get_by_filename(idx_filename),
                        created=idx_note["created"].timestamp(),
                    )
                    indexed.add(idx_filename)
                # Ignore already indexed
                else:
                    indexed.add(idx_filename)
        # Add new
        for filename in self._list_all_note_filenames():
            if filename not in indexed:
                note = self._get_by_filename(filename)
                carried_over_created = removed_created_by_mtime.pop(
                    datetime.fromtimestamp(note.last_modified), None
                )
                self._add_note_to_index(
                    writer,
                    note,
                    created=(
                        carried_over_created.timestamp()
                        if carried_over_created is not None
                        else None
                    ),
                )
                logger.info(f"'{filename}' added to index")
        writer.commit(optimize=optimize)
        logger.info("Index synchronized")

    def _sync_index_with_retry(
        self,
        optimize: bool = False,
        clean: bool = False,
        max_retries: int = 8,
        retry_delay: float = 0.25,
    ) -> None:
        for _ in range(max_retries):
            try:
                self._sync_index(optimize=optimize, clean=clean)
                return
            except LockError:
                logger.warning(f"Index locked, retrying in {retry_delay}s")
                time.sleep(retry_delay)
        logger.error(f"Failed to sync index after {max_retries} retries")

    @classmethod
    def _pre_process_search_term(cls, term):
        term = term.strip()
        # Replace "#tagname" with "tags:tagname"
        term = re.sub(
            cls.TAGS_WITH_HASH_RE,
            lambda tag: "tags:" + tag.group(0)[1:],
            term,
        )
        return term

    @staticmethod
    def _re_extract(pattern, string) -> Tuple[str, List[str]]:
        """Similar to re.sub but returns a tuple of:

        - `string` with matches removed
        - list of matches"""
        matches = []
        text = re.sub(pattern, lambda tag: matches.append(tag.group()), string)
        return (text, matches)

    @staticmethod
    def _strip_ext(filename):
        """Return the given filename without the extension."""
        return os.path.splitext(filename)[0]

    @staticmethod
    def _clear_dir(path):
        """Delete all contents of the given directory."""
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

    def _search_result_from_hit(self, hit: Hit):
        matched_fields = self._get_matched_fields(hit.matched_terms())

        title = self._strip_ext(hit["filename"])
        last_modified = hit["last_modified"].timestamp()
        created = hit["created"].timestamp()

        # If the search was ordered using a text field then hit.score is the
        # value of that field. This isn't useful so only set self._score if it
        # is a float.
        score = hit.score if type(hit.score) is float else None

        if "title" in matched_fields:
            hit.results.fragmenter = WholeFragmenter()
            title_highlights = hit.highlights("title", text=title)
        else:
            title_highlights = None

        if "content" in matched_fields:
            hit.results.fragmenter = ContextFragmenter()
            content = self._read_file(self._path_from_title(title))
            content_ex_tags, _ = FileSystemNotes._extract_tags(content)
            content_highlights = hit.highlights(
                "content",
                text=content_ex_tags,
            )
        else:
            content_highlights = None

        tag_matches = (
            [field[1] for field in hit.matched_terms() if field[0] == "tags"]
            if "tags" in matched_fields
            else None
        )

        return SearchResult(
            title=title,
            last_modified=last_modified,
            created=created,
            score=score,
            title_highlights=title_highlights,
            content_highlights=content_highlights,
            tag_matches=tag_matches,
        )

    def _fieldnames_for_term(self, term: str) -> List[str]:
        """Return a list of field names to search based on the given term. If
        the term includes a phrase then only search title and content. If the
        term does not include a phrase then also search tags."""
        fields = ["title", "content"]
        if '"' not in term:
            # If the term does not include a phrase then also search tags
            fields.append("tags")
        return fields

    @staticmethod
    def _get_matched_fields(matched_terms):
        """Return a set of matched fields from a set of ('field', 'term') "
        "tuples generated by whoosh.searching.Hit.matched_terms()."""
        return set([matched_term[0] for matched_term in matched_terms])

    @staticmethod
    def _read_file(filepath: str):
        logger.debug(f"Reading from '{filepath}'")
        with open(filepath, "r") as f:
            content = f.read()
        return content

    @staticmethod
    def _write_file(filepath: str, content: str, overwrite: bool = False):
        logger.debug(f"Writing to '{filepath}'")
        with open(filepath, "w" if overwrite else "x") as f:
            f.write(content)
