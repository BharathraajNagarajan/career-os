import { createBrowserRouter } from "react-router-dom";

import { Companies } from "../routes/Companies";
import { HomePlaceholder } from "../routes/HomePlaceholder";
import { Lanes } from "../routes/Lanes";
import { OpportunityDetail } from "../routes/OpportunityDetail";
import { Opportunities } from "../routes/Opportunities";
import { Profile } from "../routes/Profile";
import { Resumes } from "../routes/Resumes";
import { Review } from "../routes/Review";
import { Settings } from "../routes/Settings";
import { SignIn } from "../routes/SignIn";
import { Layout } from "./Layout";
import { RequireAuth } from "./RequireAuth";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { path: "sign-in", element: <SignIn /> },
      {
        element: <RequireAuth />,
        children: [
          { index: true, element: <HomePlaceholder /> },
          { path: "profile", element: <Profile /> },
          { path: "resumes", element: <Resumes /> },
          { path: "lanes", element: <Lanes /> },
          { path: "opportunities", element: <Opportunities /> },
          { path: "opportunities/:opportunityId", element: <OpportunityDetail /> },
          { path: "companies", element: <Companies /> },
          { path: "review", element: <Review /> },
          { path: "settings", element: <Settings /> },
        ],
      },
    ],
  },
]);
