export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000/api/v1";

export type Job = {
  id: string;
  code: string;
  slug: string;
  title: string;
  department: string;
  description?: string;
  location: string;
  employment_type: string;
  workplace_type: string;
  experience_level: string;
  salary_min?: number;
  salary_max?: number;
  currency: string;
  requirements: string[];
  responsibilities: string[];
  benefits: string[];
  closes_at?: string;
};

function errorMessage(data: unknown): string {
  if (!data || typeof data !== "object") {
    return "The request could not be completed.";
  }

  const detail = (
    data as { detail?: unknown }
  ).detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }

        if (
          item &&
          typeof item === "object"
        ) {
          const entry = item as {
            msg?: unknown;
            message?: unknown;
            loc?: unknown[];
          };

          const message = String(
            entry.msg ||
              entry.message ||
              "Invalid value"
          );

          const field = Array.isArray(
            entry.loc
          )
            ? entry.loc
                .filter(
                  (value) =>
                    value !== "body"
                )
                .join(" → ")
            : "";

          return field
            ? `${field}: ${message}`
            : message;
        }

        return String(item);
      })
      .filter(Boolean);

    if (messages.length) {
      return messages.join(". ");
    }
  }

  if (
    detail &&
    typeof detail === "object"
  ) {
    const entry = detail as {
      message?: unknown;
      msg?: unknown;
    };

    return String(
      entry.message ||
        entry.msg ||
        "The request could not be completed."
    );
  }

  const message = (
    data as { message?: unknown }
  ).message;

  return typeof message === "string"
    ? message
    : "The request could not be completed.";
}

export async function api<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const csrf =
    typeof document !== "undefined"
      ? document.cookie
          .split("; ")
          .find((value) =>
            value.startsWith(
              "novatech_csrf="
            )
          )
          ?.split("=")[1]
      : null;

  const isForm =
    typeof FormData !== "undefined" &&
    options.body instanceof FormData;

  const response = await fetch(
    `${API_URL}${path}`,
    {
      ...options,
      credentials: "include",
      headers: {
        ...(isForm
          ? {}
          : {
              "Content-Type":
                "application/json",
            }),
        ...(options.method &&
        options.method !== "GET" &&
        csrf
          ? {
              "X-CSRF-Token":
                decodeURIComponent(csrf),
            }
          : {}),
        ...options.headers,
      },
    }
  );

  const data = await response
    .json()
    .catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      errorMessage(data)
    );
  }

  return data;
}