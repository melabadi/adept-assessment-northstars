using Microsoft.EntityFrameworkCore;
using RequestHub.Core.Domain;

namespace RequestHub.Core.Data;

public sealed class RequestHubDbContext(DbContextOptions<RequestHubDbContext> options) : DbContext(options)
{
    public const string RequestNumberSequence = "RequestNumbers";
    public const int FirstRequestNumber = 1001;

    public DbSet<Department> Departments => Set<Department>();
    public DbSet<User> Users => Set<User>();
    public DbSet<Request> Requests => Set<Request>();
    public DbSet<ApprovalDecision> Decisions => Set<ApprovalDecision>();
    public DbSet<Comment> Comments => Set<Comment>();
    public DbSet<AttachmentMetadata> Attachments => Set<AttachmentMetadata>();
    public DbSet<AuditEvent> AuditEvents => Set<AuditEvent>();
    public DbSet<Notification> Notifications => Set<Notification>();
    public DbSet<TriageRecommendation> Recommendations => Set<TriageRecommendation>();

    protected override void OnModelCreating(ModelBuilder model)
    {
        model.HasSequence<int>(RequestNumberSequence).StartsAt(FirstRequestNumber);

        model.Entity<Department>(b =>
        {
            b.HasKey(d => d.Id);
            b.Property(d => d.Id).HasMaxLength(16);
            b.Property(d => d.NameEn).HasMaxLength(80);
            b.Property(d => d.NameFr).HasMaxLength(80);
        });

        model.Entity<User>(b =>
        {
            b.HasKey(u => u.Id);
            b.Property(u => u.Id).HasMaxLength(80);
            b.Property(u => u.DisplayName).HasMaxLength(120);
            b.Property(u => u.HomeDepartmentId).HasMaxLength(16);
            b.HasIndex(u => u.ExternalId).IsUnique();
        });

        model.Entity<Request>(b =>
        {
            b.HasKey(r => r.Id);
            b.Property(r => r.Number).HasDefaultValueSql($"nextval('\"{RequestNumberSequence}\"')");
            b.HasIndex(r => r.Number).IsUnique();
            b.Ignore(r => r.PublicId);
            b.Property(r => r.Title).HasMaxLength(120);
            b.Property(r => r.Description).HasMaxLength(4000);
            b.Property(r => r.Category).HasMaxLength(40);
            b.Property(r => r.DepartmentId).HasMaxLength(16);
            b.Property(r => r.Priority).HasConversion<string>().HasMaxLength(16);
            b.Property(r => r.Status).HasConversion<string>().HasMaxLength(16);
            b.Property(r => r.IdempotencyKey).HasMaxLength(100);
            b.Property(r => r.Version).IsRowVersion();
            b.HasIndex(r => new { r.RequesterId, r.IdempotencyKey }).IsUnique().HasFilter("\"IdempotencyKey\" IS NOT NULL");
            b.HasIndex(r => new { r.DepartmentId, r.Status });
            b.HasOne(r => r.Requester).WithMany().HasForeignKey(r => r.RequesterId).OnDelete(DeleteBehavior.Restrict);
            b.HasOne<Department>().WithMany().HasForeignKey(r => r.DepartmentId).OnDelete(DeleteBehavior.Restrict);
            b.HasOne(r => r.Decision).WithOne().HasForeignKey<ApprovalDecision>(d => d.RequestId).OnDelete(DeleteBehavior.Cascade);
            b.HasMany(r => r.Comments).WithOne().HasForeignKey(c => c.RequestId).OnDelete(DeleteBehavior.Cascade);
            b.HasMany(r => r.Attachments).WithOne().HasForeignKey(a => a.RequestId).OnDelete(DeleteBehavior.Cascade);
            b.HasMany(r => r.Recommendations).WithOne().HasForeignKey(t => t.RequestId).OnDelete(DeleteBehavior.Cascade);
        });

        model.Entity<ApprovalDecision>(b =>
        {
            b.HasKey(d => d.Id);
            // One decision per request: the database is the final guard against duplicate decisions.
            b.HasIndex(d => d.RequestId).IsUnique();
            b.Property(d => d.Outcome).HasConversion<string>().HasMaxLength(16);
            b.Property(d => d.Comment).HasMaxLength(2000);
            b.Property(d => d.IdempotencyKey).HasMaxLength(100);
            b.HasOne(d => d.DecidedBy).WithMany().HasForeignKey(d => d.DecidedById).OnDelete(DeleteBehavior.Restrict);
        });

        model.Entity<Comment>(b =>
        {
            b.HasKey(c => c.Id);
            b.Property(c => c.Body).HasMaxLength(2000);
            b.HasOne(c => c.Author).WithMany().HasForeignKey(c => c.AuthorId).OnDelete(DeleteBehavior.Restrict);
            b.HasIndex(c => new { c.RequestId, c.CreatedAt });
        });

        model.Entity<AttachmentMetadata>(b =>
        {
            b.HasKey(a => a.Id);
            b.Property(a => a.FileName).HasMaxLength(200);
            b.Property(a => a.ContentType).HasMaxLength(120);
            b.Property(a => a.StorageKey).HasMaxLength(300);
            b.Property(a => a.Sha256).HasMaxLength(64);
        });

        model.Entity<AuditEvent>(b =>
        {
            b.HasKey(a => a.Id);
            b.Property(a => a.Id).UseIdentityAlwaysColumn();
            b.Property(a => a.Action).HasMaxLength(60);
            b.Property(a => a.Actor).HasMaxLength(80);
            b.Property(a => a.Details).HasColumnType("jsonb");
            b.HasIndex(a => new { a.RequestId, a.OccurredAt });
        });

        model.Entity<Notification>(b =>
        {
            b.HasKey(n => n.Id);
            b.Property(n => n.Status).HasConversion<string>().HasMaxLength(16);
            b.Property(n => n.Type).HasMaxLength(60);
            b.Property(n => n.Recipient).HasMaxLength(80);
            b.Property(n => n.Payload).HasColumnType("jsonb");
            b.Property(n => n.LastError).HasMaxLength(1000);
            b.HasIndex(n => new { n.Status, n.NextAttemptAt });
        });

        model.Entity<TriageRecommendation>(b =>
        {
            b.HasKey(t => t.Id);
            b.Property(t => t.Version).IsRowVersion();
            b.Property(t => t.Provider).HasMaxLength(40);
            b.Property(t => t.SuggestedDepartmentId).HasMaxLength(16);
            b.Property(t => t.DepartmentAtRecommendation).HasMaxLength(16);
            b.Property(t => t.SuggestedPriority).HasConversion<string>().HasMaxLength(16);
            b.Property(t => t.Status).HasConversion<string>().HasMaxLength(16);
            b.Property(t => t.Rationale).HasMaxLength(2000);
            b.Property(t => t.ProviderTraceId).HasMaxLength(200);
            b.HasIndex(t => new { t.RequestId, t.CreatedAt });
        });
    }
}
