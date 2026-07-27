import matplotlib as mpl

# create a colormap that combines Set1, Set2 and Set3
sets = [
    mpl.colormaps[name]
    for name in ["Set1", "Set2", "Set3"]
]
colors = []
for cmap in sets:
    for i in range(cmap.N):
        rgba = cmap(i)
        if rgba[3] > 0.5:  # Only include colors with alpha > 0.5
            colors.append(rgba)
# Create a new colormap from the list of colors
combined_cmap = mpl.colors.ListedColormap(colors, name="Sets")
Sets = combined_cmap
