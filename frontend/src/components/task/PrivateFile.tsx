import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Loader2 } from "lucide-react";

import { cn, errorMessage } from "@/lib/utils";
import { toast } from "@/stores/toast";

function useBlobUrl(queryKey: readonly unknown[], fetcher: () => Promise<Blob>, enabled: boolean) {
  const query = useQuery({
    queryKey,
    queryFn: async () => {
      const blob = await fetcher();
      return URL.createObjectURL(blob);
    },
    enabled,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  });

  useEffect(() => {
    const url = query.data;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [query.data]);

  return query;
}

export function PrivateImage({
  queryKey,
  fetcher,
  alt,
  className,
}: {
  queryKey: readonly unknown[];
  fetcher: () => Promise<Blob>;
  alt: string;
  className?: string;
}) {
  const { data, isLoading, isError } = useBlobUrl(queryKey, fetcher, true);

  if (isLoading) {
    return (
      <div className={cn("flex items-center justify-center rounded-lg bg-slate-100", className)}>
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-hidden />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className={cn("flex items-center justify-center rounded-lg bg-slate-100 text-xs text-slate-400", className)}>
        Preview unavailable
      </div>
    );
  }
  return (
    <a href={data} target="_blank" rel="noreferrer" className={cn("block overflow-hidden rounded-lg", className)}>
      <img src={data} alt={alt} className="h-full w-full object-cover" />
    </a>
  );
}

export function PrivateFileButton({
  fetcher,
  label,
  className,
}: {
  fetcher: () => Promise<Blob>;
  label: string;
  className?: string;
}) {
  const [busy, setBusy] = useState(false);

  const open = async () => {
    setBusy(true);
    try {
      const blob = await fetcher();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={() => void open()}
      disabled={busy}
      className={cn("inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:underline", className)}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : (
        <FileText className="h-3.5 w-3.5" aria-hidden />
      )}
      {label}
    </button>
  );
}
