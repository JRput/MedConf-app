import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-bg">
      <div className="mx-auto max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
        <Skeleton className="mb-5 h-5 w-48" />

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
          <main className="min-w-0 space-y-8">
            <div className="space-y-3">
              <div className="flex gap-2">
                <Skeleton className="h-5 w-24" />
                <Skeleton className="h-5 w-20" />
              </div>
              <Skeleton className="h-9 w-4/5" />
            </div>

            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>

            <div className="space-y-3">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-40 w-full rounded-lg" />
            </div>
          </main>

          <Skeleton className="hidden h-80 w-full rounded-lg lg:block" />
        </div>
      </div>
    </div>
  )
}
