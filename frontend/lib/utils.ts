import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { formatDistanceToNow, format } from "date-fns";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatRelativeTime(date: string | null | undefined): string {
  if (!date) return "";
  try {
    return formatDistanceToNow(new Date(date), { addSuffix: true });
  } catch {
    return "";
  }
}

export function formatTime(date: string | null | undefined): string {
  if (!date) return "";
  try {
    return format(new Date(date), "HH:mm");
  } catch {
    return "";
  }
}

export function formatDate(date: string | null | undefined): string {
  if (!date) return "";
  try {
    return format(new Date(date), "MMM d, yyyy");
  } catch {
    return "";
  }
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "...";
}

export function getInitials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

export function getStatusColor(status: string): string {
  switch (status) {
    case "connected": return "text-green-500";
    case "connecting": return "text-yellow-500";
    case "disconnected": return "text-gray-400";
    case "error": return "text-red-500";
    default: return "text-gray-400";
  }
}

export function getStatusDot(status: string): string {
  switch (status) {
    case "connected": return "bg-green-500";
    case "connecting": return "bg-yellow-500 animate-pulse";
    case "disconnected": return "bg-gray-400";
    case "error": return "bg-red-500";
    default: return "bg-gray-400";
  }
}
