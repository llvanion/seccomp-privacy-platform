import { useQuery, useMutation, type UseMutationOptions, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { useToast } from "@/components/toast";

export type ApiQueryOptions<T> = Omit<UseQueryOptions<T, ApiError>, "queryKey" | "queryFn">;

export function useApiQuery<T>(
  key: ReadonlyArray<unknown>,
  fetcher: () => Promise<T>,
  options?: ApiQueryOptions<T>,
): UseQueryResult<T, ApiError> {
  return useQuery<T, ApiError>({
    queryKey: key,
    queryFn: fetcher,
    ...options,
  });
}

export function useApiMutation<TData, TVars>(
  fn: (vars: TVars) => Promise<TData>,
  options?: UseMutationOptions<TData, ApiError, TVars> & { successToast?: string; errorToast?: boolean },
) {
  const toast = useToast();
  return useMutation<TData, ApiError, TVars>({
    mutationFn: fn,
    onSuccess: (data, vars, ctx, meta) => {
      if (options?.successToast) toast.pushSuccess(options.successToast);
      options?.onSuccess?.(data, vars, ctx, meta);
    },
    onError: (err, vars, ctx, meta) => {
      if (options?.errorToast !== false) toast.pushError("操作失败", err.message);
      options?.onError?.(err, vars, ctx, meta);
    },
    ...(options ?? {}),
  });
}
