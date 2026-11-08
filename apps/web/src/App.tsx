import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, Route, Routes } from "react-router";

import { ApiError } from "@/api/client";
import { AuthProvider } from "@/auth/AuthContext";
import LoginPage from "@/auth/LoginPage";
import { RequireAuth, RequireRead } from "@/auth/guards";
import AppShell, { Home } from "@/components/AppShell";
import ContactsPage from "@/features/contacts/ContactsPage";
import LogsPage from "@/features/logs/LogsPage";
import MessagesPage from "@/features/messages/MessagesPage";
import UsersPage from "@/features/users/UsersPage";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 4xx will not get better by asking again; a dropped connection might.
        retry: (count, error) => !(error instanceof ApiError) && count < 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export default function App() {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppShell />}>
              <Route index element={<Home />} />
              <Route element={<RequireRead resource="messages" />}>
                <Route path="messages" element={<MessagesPage />} />
              </Route>
              <Route element={<RequireRead resource="contacts" />}>
                <Route path="contacts" element={<ContactsPage />} />
              </Route>
              <Route element={<RequireRead resource="users" />}>
                <Route path="users" element={<UsersPage />} />
              </Route>
              <Route element={<RequireRead resource="logs" />}>
                <Route path="logs" element={<LogsPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </QueryClientProvider>
  );
}
