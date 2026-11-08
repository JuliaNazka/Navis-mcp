using System.Collections.Generic;
using Autodesk.Navisworks.Api;
using Autodesk.Navisworks.Api.Clash;

namespace NavisCoord
{
    /// <summary>
    /// Navis-mcp: one place for the clash-test collection API, which changed in
    /// Navisworks 2027.
    ///
    /// Up to 2026 <c>DocumentClashTests.Tests</c> was a flat collection and
    /// <c>TestsAddCopy</c>/<c>TestsRemove</c> took only the item. From 2027 clash
    /// tests live in folders: the root is <c>Value.TestsRoot</c>
    /// (a <c>ClashTestFolder</c>) and add/remove take the parent group.
    ///
    /// <see cref="Tests"/> returns every test in the document, in tree order,
    /// so callers that matched by name or GUID keep working when tests sit in
    /// sub-folders. It is a snapshot: re-read it after a write.
    /// </summary>
    internal static class ClashCompat
    {
        public static List<SavedItem> Tests(DocumentClashTests data)
        {
#if NAVIS2027
            var all = new List<SavedItem>();
            Collect(data.Value.TestsRoot, all);
            return all;
#else
            return new List<SavedItem>(data.Tests);
#endif
        }

        public static void AddCopy(DocumentClashTests data, SavedItem item)
        {
#if NAVIS2027
            data.TestsAddCopy(data.Value.TestsRoot, item);
#else
            data.TestsAddCopy((ClashTest)item);
#endif
        }

        public static void Remove(DocumentClashTests data, SavedItem item)
        {
#if NAVIS2027
            data.TestsRemove(item.Parent ?? data.Value.TestsRoot, item);
#else
            data.TestsRemove((ClashTest)item);
#endif
        }

#if NAVIS2027
        private static void Collect(GroupItem folder, List<SavedItem> into)
        {
            foreach (var child in folder.Children)
            {
                if (child is ClashTest)
                    into.Add(child);
                else if (child is ClashTestFolder sub)
                    Collect(sub, into);
            }
        }
#endif
    }
}
