import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <p className="text-sm font-semibold text-navy-600">404</p>
      <h1 className="mt-1 text-xl font-semibold text-slate-900">Page not found</h1>
      <p className="mt-2 text-sm text-slate-600">The page does not exist, or the resource is not visible to your role and tenant.</p>
      <Link to="/" className="mt-4 inline-block text-sm font-medium text-navy-700 underline">Back to overview</Link>
    </div>
  );
}
