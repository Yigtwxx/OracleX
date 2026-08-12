'use client';

import { useState } from 'react';
import { FileText, PenLine, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useCreateNote, useDeleteNote, useNotes } from '@/hooks/queries';

/**
 * The right-hand notes pane, header included.
 *
 * The header's compose toggle drives the same `isCreatingNote` state as the
 * form, so the whole pane lives in one component rather than lifting that state
 * into the page shell.
 */
export default function NotesPanel() {
  const [noteTitle, setNoteTitle] = useState('');
  const [noteContent, setNoteContent] = useState('');
  const [isCreatingNote, setIsCreatingNote] = useState(false);

  const { data: notes = [], isLoading: loadingNotes } = useNotes();
  const createNoteMutation = useCreateNote();
  const deleteNoteMutation = useDeleteNote();

  const handleCreateNote = () => {
    if (!noteTitle.trim() || !noteContent.trim()) return;
    createNoteMutation.mutate(
      { title: noteTitle, content: noteContent },
      {
        onSuccess: () => {
          setNoteTitle('');
          setNoteContent('');
          setIsCreatingNote(false);
        },
      }
    );
  };

  const handleDeleteNote = (id: string) => {
    if (!confirm('Delete this note?')) return;
    deleteNoteMutation.mutate(id);
  };

  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <PenLine className="w-3.5 h-3.5 text-fg-muted" />
          <h2 className="text-md font-semibold text-fg">My Notes</h2>
        </div>
        <button
          onClick={() => setIsCreatingNote(!isCreatingNote)}
          aria-label={isCreatingNote ? 'Cancel new note' : 'Create note'}
          className={`p-1.5 rounded-md border border-line text-fg-muted hover:text-fg hover:border-line-strong transition-transform ${isCreatingNote ? 'rotate-45' : ''}`}
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar space-y-3">
        {isCreatingNote && (
          <div className="surface p-3">
            <input
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              placeholder="Note title"
              className="w-full bg-transparent border-none text-md font-semibold text-fg placeholder:text-fg-subtle focus:outline-none mb-2"
              autoFocus
            />
            <textarea
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              placeholder="Write your thoughts here…"
              className="w-full bg-surface-2 border border-line rounded-md p-2.5 text-base text-fg-muted min-h-[100px] mb-3 resize-none focus:outline-none focus:border-accent"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setIsCreatingNote(false)}
                className="px-2.5 py-1 text-sm text-fg-muted hover:text-fg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateNote}
                disabled={!noteTitle || !noteContent || createNoteMutation.isPending}
                className="px-2.5 py-1 bg-accent text-white text-sm rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
        )}

        {loadingNotes ? (
          <div className="text-center py-10">
            <RefreshCw className="w-4 h-4 text-fg-subtle animate-spin mx-auto" />
          </div>
        ) : notes.length === 0 && !isCreatingNote ? (
          <div className="text-center py-10 border border-dashed border-line rounded-lg">
            <FileText className="w-5 h-5 text-fg-subtle mx-auto mb-2" />
            <p className="text-base text-fg-subtle">No notes yet.</p>
          </div>
        ) : (
          notes.map((note) => (
            <div
              key={note.id}
              className="surface p-3 group hover:border-line-strong transition-colors"
            >
              <div className="flex justify-between items-start gap-3 mb-1.5">
                <h3 className="text-base font-semibold text-fg truncate">{note.title}</h3>
                <button
                  onClick={() => handleDeleteNote(note.id)}
                  aria-label={`Delete note ${note.title}`}
                  className="shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-fg-subtle hover:text-down transition-opacity"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="text-base text-fg-muted line-clamp-4 whitespace-pre-wrap">
                {note.content}
              </p>
              <div className="mt-2.5 pt-2.5 border-t border-line flex justify-end">
                <span className="text-2xs font-mono tabnum text-fg-subtle">
                  {new Date(note.date).toLocaleDateString('en-GB')}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </>
  );
}
