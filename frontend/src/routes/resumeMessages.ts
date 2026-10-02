import { ApiRequestError } from "../api/client";

const UPLOAD_ERRORS: Record<string, string> = {
  resume_too_large: "That file is too large.",
  unsupported_file_type: "Only PDF and Word (.docx) files are supported.",
  unsafe_document: "That document could not be accepted safely.",
  duplicate_resume: "You have already uploaded this exact file.",
  lane_not_active: "That lane is archived.",
};

const EXTRACTION_ERRORS: Record<string, string> = {
  too_many_pages: "This file has more pages than allowed.",
  encrypted: "This PDF is password protected.",
  unreadable: "No text could be read from this file. Scanned images are not supported yet.",
  parse_timeout: "Reading this file took too long.",
};

const LANE_ERRORS: Record<string, string> = {
  lane_name_taken: "You already have an active lane with that name.",
  invalid_default_resume: "The default must be an active resume assigned to this lane.",
  lane_not_active: "That lane is archived.",
};

function lookup(table: Record<string, string>, error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return table[error.code] ?? fallback;
  }
  return fallback;
}

export function uploadErrorMessage(error: unknown): string {
  return lookup(UPLOAD_ERRORS, error, "Upload failed. Please try again.");
}

export function laneErrorMessage(error: unknown): string {
  return lookup(LANE_ERRORS, error, "Could not save the lane. Please try again.");
}

export function extractionMessage(status: string, code: string | null | undefined): string {
  if (status === "pending") {
    return "Processing…";
  }
  if (status === "succeeded") {
    return "Ready";
  }
  return EXTRACTION_ERRORS[code ?? ""] ?? "This file could not be processed.";
}
