import { products } from "../data/products";

export const ProductGrid = () => (
  <div className="grid">
    {products.map((product) => (
      <div key={product.name} className="card">
        <div className="card-header">
          <div>
            <p className="eyebrow">{product.category}</p>
            <h3>{product.name}</h3>
          </div>
          <span className="pill">:{product.port}</span>
        </div>
        <p>{product.description}</p>
      </div>
    ))}
  </div>
);
