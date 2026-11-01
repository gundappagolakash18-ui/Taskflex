import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { format, formatDistanceToNow, parseISO } from "date-fns";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatMoney(amount: number | null | undefined, currency = "INR"): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

export function formatDate(value: string | null | undefined, pattern = "d MMM yyyy"): string {
  if (!value) return "—";
  try {
    return format(parseISO(value), pattern);
  } catch {
    return value;
  }
}

export function formatDateTime(value: string | null | undefined): string {
  return formatDate(value, "d MMM yyyy, h:mm a");
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return "";
  try {
    return formatDistanceToNow(parseISO(value), { addSuffix: true });
  } catch {
    return "";
  }
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

export function scorePercent(score: number): number {
  return Math.round(score * 100);
}

export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return (error as { message: string }).message;
  }
  return "Something went wrong. Please try again.";
}
