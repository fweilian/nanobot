import { ChevronDown, ChevronRight, Wrench } from 'lucide-react';
import type { ComponentPropsWithoutRef } from 'react';
import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useConfigStore } from '../../stores/configStore';
import type { Message, MessageBlock, ToolCallBlock } from '../../types';

interface MessageProps {
  message: Message;
}

function isSafeHref(href?: string) {
  return !!href && /^(https?:|mailto:)/i.test(href);
}

function isProtectedMediaSrc(src?: string) {
  if (!src) {
    return false;
  }
  return /^\/v1\/media\//.test(src) || /\/v1\/media\//.test(src);
}

function resolveApiUrl(apiUrl: string, src: string) {
  if (/^https?:\/\//i.test(src)) {
    return src;
  }
  const base = apiUrl.replace(/\/$/, '');
  const path = src.startsWith('/') ? src : `/${src}`;
  return `${base}${path}`;
}

function AuthenticatedImage({
  src,
  alt,
  ...props
}: ComponentPropsWithoutRef<'img'>) {
  const { apiUrl, apiKey } = useConfigStore();
  const [resolvedSrc, setResolvedSrc] = useState<string | undefined>(undefined);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!src) {
      setResolvedSrc(undefined);
      return;
    }

    if (!isProtectedMediaSrc(src)) {
      setResolvedSrc(src);
      return;
    }

    let active = true;
    let objectUrl: string | null = null;

    const fetchProtectedMedia = async () => {
      try {
        const target = resolveApiUrl(apiUrl, src);
        const headers = new Headers();
        if (apiKey) {
          headers.set('Authorization', `Bearer ${apiKey}`);
        }
        const response = await fetch(target, { headers });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (active) {
          setResolvedSrc(objectUrl);
          setError(false);
        }
      } catch {
        if (active) {
          setResolvedSrc(undefined);
          setError(true);
        }
      }
    };

    void fetchProtectedMedia();

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [apiKey, apiUrl, src]);

  if (error) {
    return <span className="text-sm text-red-500">[image failed to load]</span>;
  }

  if (!resolvedSrc) {
    return <span className="text-sm text-gray-500">[loading image]</span>;
  }

  return <img {...props} src={resolvedSrc} alt={alt} className="max-w-full rounded-lg" />;
}

function MarkdownBlock({ block, isUser }: { block: Extract<MessageBlock, { type: 'markdown' }>; isUser: boolean }) {
  const Link = ({ href, children }: ComponentPropsWithoutRef<'a'>) =>
    isSafeHref(href) ? (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    );

  const InlineCode = ({
    className,
    children,
    ...props
  }: ComponentPropsWithoutRef<'code'>) => (
    <code
      {...props}
      className={`${className || ''} rounded bg-black/10 px-1 py-0.5 dark:bg-white/10`}
    >
      {children}
    </code>
  );

  const Pre = ({ children }: ComponentPropsWithoutRef<'pre'>) => (
    <pre className="overflow-x-auto rounded-lg bg-black/10 p-3 dark:bg-white/10">
      {children}
    </pre>
  );

  return (
    <div className={`prose prose-sm max-w-none break-words ${isUser ? 'prose-invert' : 'dark:prose-invert'}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: Link,
          code: InlineCode,
          img: AuthenticatedImage,
          pre: Pre,
        }}
      >
        {block.content || '...'}
      </ReactMarkdown>
    </div>
  );
}

function ToolCallCard({ block }: { block: ToolCallBlock }) {
  const [open, setOpen] = useState(block.status !== 'completed');
  const statusTone = useMemo(() => {
    switch (block.status) {
      case 'failed':
        return 'border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200';
      case 'completed':
        return 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200';
      case 'streaming':
        return 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200';
      default:
        return 'border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200';
    }
  }, [block.status]);

  return (
    <div className={`rounded-xl border p-3 ${statusTone}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <Wrench size={16} />
        <span className="font-medium">{block.toolName}</span>
        <span className="ml-auto text-xs uppercase tracking-wide">{block.status}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-3 text-sm">
          {block.argsText && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-70">Args</div>
              <pre className="overflow-x-auto rounded-lg bg-black/10 p-2 dark:bg-white/10">
                <code>{block.argsText}</code>
              </pre>
            </div>
          )}
          {block.resultText && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-70">Result</div>
              <pre className="overflow-x-auto rounded-lg bg-black/10 p-2 dark:bg-white/10">
                <code>{block.resultText}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 shadow-sm ${
          isUser
            ? 'bg-indigo-600 text-white'
            : 'bg-white text-gray-900 dark:bg-gray-800 dark:text-white'
        }`}
      >
        <div className="space-y-3">
          {message.blocks.map((block) => {
            if (block.type === 'markdown') {
              return <MarkdownBlock key={block.id} block={block} isUser={isUser} />;
            }
            if (block.type === 'tool_call') {
              return <ToolCallCard key={block.id} block={block} />;
            }
            return (
              <div
                key={block.id}
                className="rounded-lg border border-dashed border-gray-300 px-3 py-2 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400"
              >
                {block.label}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
