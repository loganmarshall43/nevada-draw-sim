import { doc, getDoc, serverTimestamp, setDoc } from "firebase/firestore";
import type { User } from "firebase/auth";
import { db } from "../../firebase/firebase";

export async function ensureUserProfile(user: User) {
  const ref = doc(db, "users", user.uid);
  const snap = await getDoc(ref);

  if (!snap.exists()) {
    await setDoc(ref, {
      email: user.email ?? null,
      createdAt: serverTimestamp(),
      // app defaults for later
      state: "NV",
      bonusPoints: {
        elk: 0,
        deer: 0,
        antelope: 0,
        sheep: 0,
        goat: 0,
      },
      favorites: [],
    });
  }
}
