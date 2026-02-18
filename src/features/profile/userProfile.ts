import { doc, getDoc, setDoc } from "firebase/firestore";
import { db } from "../../firebase/firebase";

export type SpeciesKey = "elk" | "deer" | "antelope" | "sheep" | "goat";

export type UserProfile = {
  email: string | null;
  state: "NV";
  bonusPoints: Record<SpeciesKey, number>;
};

export async function getUserProfile(uid: string) {
  const ref = doc(db, "users", uid);
  const snap = await getDoc(ref);
  return snap.exists() ? (snap.data() as UserProfile) : null;
}

export async function setBonusPoints(uid: string, species: SpeciesKey, value: number) {
  const ref = doc(db, "users", uid);
  await setDoc(
    ref,
    { bonusPoints: { [species]: value } },
    { merge: true }
  );
}
